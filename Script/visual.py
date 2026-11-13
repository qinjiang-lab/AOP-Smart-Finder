#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import re
from pathlib import Path
from collections import defaultdict
import pandas as pd
import networkx as nx
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

# ============================================================
# 1. Configuration
# ============================================================

input_word = os.environ.get("INPUT_WORD", "").strip()

if not input_word:
    raise SystemExit(
        "No INPUT_WORD has been received. "
        "Please run it via bat or set it in the environment variables."
    )

BASE_DIR = Path("./") / input_word

FINDER_PATH = BASE_DIR / "Finder.json"
SKIPPED_PATH = BASE_DIR / "Finder_skipped.json"
WOS_PATH = BASE_DIR / "wos_articles.json"

OUTPUT_XLSX = BASE_DIR / "AOP_network.xlsx"
OUTPUT_TXT = BASE_DIR / "AOP_articles.txt"

FULLTEXT_DIR = BASE_DIR / "Fulltext"
FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)

# Minimum number of supporting articles required for an edge.
MIN_SUPPORT = 1

# AOP-Wiki KE page URL.
AOP_WIKI_KE_URL = "https://aopwiki.org/events/"

# Maximum number of supporting article columns.
# Set to None to include all supporting articles.
MAX_DOI_COLUMNS = None


# ============================================================
# 2. JSON Loading
# ============================================================

def load_json(path):
    """Load a JSON file."""

    if not path.exists():
        print(f"[WARNING] File not found: {path}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON format in file: {path}"
        ) from exc


def normalize_records(data):
    """Normalize JSON data into a list of article dictionaries."""

    if isinstance(data, list):
        return [
            item for item in data
            if isinstance(item, dict)
        ]

    if not isinstance(data, dict):
        return []

    possible_keys = [
        "articles",
        "Articles",
        "records",
        "Records",
        "results",
        "Results",
        "data",
        "Data"
    ]

    for key in possible_keys:

        value = data.get(key)

        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, dict)
            ]

    article_keys = {
        "UT",
        "Article Title",
        "Title",
        "Abstract",
        "Events",
        "DOI"
    }

    if article_keys.intersection(data.keys()):
        return [data]

    records = []

    for key, value in data.items():

        if isinstance(value, dict):

            item = value.copy()

            if not item.get("UT"):
                item["UT"] = key

            records.append(item)

    return records


def count_records(data):
    """Count records in a JSON structure."""

    if isinstance(data, list):
        return len(data)

    if not isinstance(data, dict):
        return 0

    possible_keys = [
        "articles",
        "Articles",
        "records",
        "Records",
        "results",
        "Results",
        "data",
        "Data",
        "skipped",
        "Skipped"
    ]

    for key in possible_keys:

        value = data.get(key)

        if isinstance(value, list):
            return len(value)

    article_keys = {
        "UT",
        "Article Title",
        "Title",
        "Abstract",
        "Events"
    }

    if article_keys.intersection(data.keys()):
        return 1

    return len(data)


# Load input files.
finder_raw = load_json(FINDER_PATH)
skipped_raw = load_json(SKIPPED_PATH)
wos_raw = load_json(WOS_PATH)

finder_data = normalize_records(finder_raw)
wos_data = normalize_records(wos_raw)

# Article processing statistics.
processed_count = len(finder_data)
skipped_count = count_records(skipped_raw)
total_count = processed_count + skipped_count


# ============================================================
# 3. Build UT -> DOI Mapping from wos_articles.json
# ============================================================

def normalize_doi(doi):
    if doi is None:
        return ""
    return str(doi).strip()


def is_valid_doi(identifier):
    """Check whether an identifier has a DOI-like format."""

    if not identifier:
        return False

    return bool(
        re.match(
            r"^10\.\d{4,9}/\S+$",
            str(identifier).strip(),
            flags=re.IGNORECASE
        )
    )


ut_to_doi = {}

for article in wos_data:

    ut = str(article.get("UT") or "").strip()
    doi = normalize_doi(article.get("DOI"))

    if ut:
        ut_to_doi[ut] = doi

valid_doi_count = sum(
    1 for doi in ut_to_doi.values()
    if is_valid_doi(doi)
)

missing_doi_count = len(ut_to_doi) - valid_doi_count


# ============================================================
# 4. Article Information Extraction
# ============================================================

def get_article_ut(article):
    return str(
        article.get("UT")
        or article.get("ut")
        or article.get("Article UT")
        or ""
    ).strip()


def get_article_title(article):
    return str(
        article.get("Article Title")
        or article.get("Title")
        or article.get("title")
        or ""
    ).strip()


def get_article_abstract(article):
    return str(
        article.get("Abstract")
        or article.get("abstract")
        or ""
    ).strip()


# ============================================================
# 5. Event Extraction
# ============================================================

def get_events(article):
    """Extract the Events field from an article."""

    events = article.get("Events")

    if events is None:
        events = article.get("events")

    if events is None:
        return []

    if isinstance(events, list):
        return [
            event for event in events
            if isinstance(event, dict)
        ]

    if isinstance(events, dict):

        if (
                "upevent" in events
                or "downevent" in events
                or "upEvent" in events
                or "downEvent" in events
        ):
            return [events]

        return [
            value for value in events.values()
            if isinstance(value, dict)
        ]

    return []


def get_event_value(event, possible_keys):
    for key in possible_keys:

        value = event.get(key)

        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def clean_event_name(name):
    if not name:
        return ""

    return re.sub(r"\s+", " ", str(name)).strip()


def get_event_ke_id(event_name):
    if not event_name:
        return ""
    m = re.search(r"\((?:KE)?(\d+)\)", str(event_name), flags=re.IGNORECASE)
    if m:
        return f"KE{m.group(1)}"
    return ""


# ============================================================
# 6. Aggregate Source -> Target Relationships
# ============================================================

article_stats = []

# {(source, target): {UT: article information}}
edge_articles = defaultdict(dict)

# {(source, target): set of species reported for that relationship}
edge_species = defaultdict(set)

# {UT: article information}
all_article_text = {}

total_events = 0
articles_with_events = 0

for article in finder_data:

    ut = get_article_ut(article)
    title = get_article_title(article)
    abstract = get_article_abstract(article)

    events = get_events(article)

    if events:
        articles_with_events += 1

    total_events += len(events)

    if ut:
        all_article_text[ut] = {
            "title": title,
            "abstract": abstract
        }

    for event in events:

        source = get_event_value(
            event,
            [
                "upevent",
                "upEvent",
                "source",
                "Source"
            ]
        )

        target = get_event_value(
            event,
            [
                "downevent",
                "downEvent",
                "target",
                "Target"
            ]
        )

        source = clean_event_name(source)
        target = clean_event_name(target)

        if not source or not target:
            continue

        if source == target:
            continue

        edge_key = (source, target)

        # Collect species from the individual event in Finder.json.
        # Species are aggregated and deduplicated for each Source -> Target pair.
        species_value = event.get("species")

        if isinstance(species_value, (list, tuple, set)):
            species_values = species_value
        else:
            species_values = [species_value]

        for species_item in species_values:

            species = str(species_item or "").strip()

            if species:
                edge_species[edge_key].add(species)

        if ut:
            edge_articles[edge_key][ut] = {
                "Title": title,
                "Abstract": abstract
            }

# ============================================================
# 7. Build Edge Records and Resolve Supporting Identifiers
# ============================================================

edge_records = []

for (source, target), supporting_articles in edge_articles.items():

    support_uts = sorted(supporting_articles.keys())

    if len(support_uts) < MIN_SUPPORT:
        continue

    identifiers = []

    for ut in support_uts:
        # DOI is retrieved from wos_articles.json through UT.
        # Finder.json is not used as a DOI source.
        doi = ut_to_doi.get(ut, "")

        # Use WOS UT when DOI is unavailable.
        identifier = doi if doi else ut

        identifiers.append(identifier)

    if MAX_DOI_COLUMNS is not None:
        identifiers = identifiers[:MAX_DOI_COLUMNS]

    species_values = sorted(
        edge_species.get((source, target), set()),
        key=str.casefold
    )

    edge_records.append({
        "Source": source,
        "Target": target,
        "Count": len(support_uts),
        "Species": "; ".join(species_values),
        "Verification_Status": "Not_checked",
        "_UTs": support_uts,
        "_Identifiers": identifiers
    })


# ============================================================
# 7.1 Calculate Unique KE and KER Statistics
# ============================================================

def is_stressor_event(event_name):
    """Return True when an event label represents a stressor, not a KE."""

    return bool(
        re.search(
            r"\(\s*stressor\s*\)\s*$",
            str(event_name),
            flags=re.IGNORECASE
        )
    )


OFFICIAL_KE_RE = re.compile(r"\((?:KE)?(\d+)\)", re.IGNORECASE)


def get_official_ke_number(event_name):
    """提取 (KE123) 或 (123) 里的数字；不是官方 KE 则返回 None。"""
    event_name = clean_event_name(event_name)
    if not event_name or is_stressor_event(event_name):
        return None
    m = OFFICIAL_KE_RE.search(event_name)
    return m.group(1) if m else None


unique_ke_names = set()      # 直接按字符串去重
official_ke_numbers = set()  # 按 (KE123)/(123) 里的数字去重

for record in edge_records:
    for event_name in (record["Source"], record["Target"]):
        name = clean_event_name(event_name)
        if not name or is_stressor_event(name):
            continue
        unique_ke_names.add(name)                 # 字符串口径
        ke_number = get_official_ke_number(name)  # 官方 KE 口径
        if ke_number is not None:
            official_ke_numbers.add(ke_number)

total_unique_ke_count = len(unique_ke_names)
official_unique_ke_count = len(official_ke_numbers)
total_ker_count = len(edge_records)

# ============================================================
# 8. Build Directed Graph and Identify Root Nodes
# ============================================================

G = nx.DiGraph()

for record in edge_records:
    G.add_edge(
        record["Source"],
        record["Target"],
        weight=record["Count"]
    )

# Root nodes are nodes with an in-degree of zero.
root_nodes = {
    node for node in G.nodes()
    if G.in_degree(node) == 0
}

# ============================================================
# 9. Identify Network Groups Excluding Root Nodes
# ============================================================

# Remove root nodes before identifying connected components.
non_root_nodes = set(G.nodes()) - root_nodes

non_root_graph = G.subgraph(
    non_root_nodes
).to_undirected()

components = list(
    nx.connected_components(non_root_graph)
)

components.sort(
    key=lambda component: (
        -len(component),
        tuple(sorted(str(node) for node in component))
    )
)

node_to_group = {}

for i, component in enumerate(components, start=1):

    group_name = f"G{i}"

    for node in component:
        node_to_group[node] = group_name

# ============================================================
# 10. Assign Each Edge to a Network Group
# ============================================================

for record in edge_records:

    source = record["Source"]
    target = record["Target"]

    if source in root_nodes and target not in root_nodes:

        group = node_to_group.get(target, "Unassigned")

    elif target in root_nodes and source not in root_nodes:

        group = node_to_group.get(source, "Unassigned")

    else:

        group = node_to_group.get(
            source,
            node_to_group.get(target, "Unassigned")
        )

    record["Group"] = group

for group_name in sorted(
        set(record["Group"] for record in edge_records)
):
    count = sum(
        1 for record in edge_records
        if record["Group"] == group_name
    )

# ============================================================
# 11. Prepare Excel DataFrames
# ============================================================

max_doi_columns = max(
    (
        len(record["_Identifiers"])
        for record in edge_records
    ),
    default=0
)

doi_headers = [
    f"DOI_{i}"
    for i in range(1, max_doi_columns + 1)
]

base_headers = [
    "Group",
    "Source",
    "Target",
    "Count",
    "Species",
    "Verification_Status"
]

all_headers = base_headers + doi_headers


def make_edge_dataframe(records):
    """Convert edge records into a DataFrame."""

    rows = []

    for record in records:

        row = {
            "Group": record["Group"],
            "Source": record["Source"],
            "Target": record["Target"],
            "Count": record["Count"],
            "Species": record["Species"],
            "Verification_Status": record["Verification_Status"]
        }

        identifiers = record["_Identifiers"]

        for i, header in enumerate(doi_headers):

            if i < len(identifiers):
                row[header] = identifiers[i]
            else:
                row[header] = ""

        rows.append(row)

    return pd.DataFrame(
        rows,
        columns=all_headers
    )


all_edges_df = make_edge_dataframe(edge_records)

# Article_Stats contains summary statistics only.
article_stats_df = pd.DataFrame(
    [{
        "Processed_Articles": processed_count,
        "Skipped_Articles": skipped_count,
        "Total_Articles": total_count,
        "Total_Unique_KEs": total_unique_ke_count,
        "Official_Unique_KEs": official_unique_ke_count,
        "Total_Unique_KERs": total_ker_count
    }]
)

# ============================================================
# 12. Create Summary Worksheet
# ============================================================

summary_records = []

group_names = sorted(
    set(
        record["Group"]
        for record in edge_records
    ),
    key=lambda x: (
        int(x[1:])
        if x.startswith("G") and x[1:].isdigit()
        else 999999
    )
)

for group_name in group_names:

    group_records = [
        record for record in edge_records
        if record["Group"] == group_name
    ]

    group_nodes = set()

    for record in group_records:
        group_nodes.add(record["Source"])
        group_nodes.add(record["Target"])

    group_support_uts = set()

    for record in group_records:
        group_support_uts.update(record["_UTs"])

    group_roots = sorted(
        node
        for node in group_nodes
        if node in root_nodes
    )

    summary_records.append({
        "Group": group_name,
        "Nodes": len(group_nodes),
        "Edges": len(group_records),
        "Supporting_Articles": len(group_support_uts),
        "Root_Nodes": "; ".join(group_roots)
    })

summary_df = pd.DataFrame(
    summary_records,
    columns=[
        "Group",
        "Nodes",
        "Edges",
        "Supporting_Articles",
        "Root_Nodes"
    ]
)

# ============================================================
# 13. Export Excel Workbook
# ============================================================

with pd.ExcelWriter(
        OUTPUT_XLSX,
        engine="openpyxl"
) as writer:
    article_stats_df.to_excel(
        writer,
        sheet_name="Article_Stats",
        index=False
    )

    summary_df.to_excel(
        writer,
        sheet_name="Summary",
        index=False
    )

    all_edges_df.to_excel(
        writer,
        sheet_name="All_Edges",
        index=False
    )

    for group_name in group_names:
        group_records = [
            record for record in edge_records
            if record["Group"] == group_name
        ]

        group_df = make_edge_dataframe(group_records)

        group_df.to_excel(
            writer,
            sheet_name=group_name[:31],
            index=False
        )

# ============================================================
# 14. Format Excel Workbook and Add Hyperlinks
# ============================================================

wb = load_workbook(OUTPUT_XLSX)

header_fill = PatternFill(
    fill_type="solid",
    fgColor="D9EAF7"
)

header_font = Font(
    bold=True,
    color="000000"
)

for ws in wb.worksheets:

    ws.freeze_panes = "A2"

    # Keep Excel column filtering enabled.
    ws.auto_filter.ref = ws.dimensions

    # Format header row.
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )

    # Automatically adjust column widths.
    for column_cells in ws.columns:

        max_length = 0

        column_letter = get_column_letter(
            column_cells[0].column
        )

        for cell in column_cells:

            if cell.value is not None:
                max_length = max(
                    max_length,
                    len(str(cell.value))
                )

        ws.column_dimensions[column_letter].width = min(
            max(max_length + 2, 12),
            60
        )

    header_map = {
        cell.value: cell.column
        for cell in ws[1]
    }

    # --------------------------------------------------------
    # Add AOP-Wiki hyperlinks to Source and Target KE IDs.
    # --------------------------------------------------------

    for column_name in ["Source", "Target"]:

        if column_name not in header_map:
            continue

        col = header_map[column_name]

        for row in range(2, ws.max_row + 1):

            cell = ws.cell(
                row=row,
                column=col
            )

            if not cell.value:
                continue

            ke_id = get_event_ke_id(
                str(cell.value)
            )

            if ke_id:
                ke_number = re.search(
                    r"\d+",
                    ke_id
                ).group(0)

                cell.hyperlink = (
                    f"{AOP_WIKI_KE_URL}{ke_number}"
                )

                cell.style = "Hyperlink"

    # --------------------------------------------------------
    # Add DOI hyperlinks to DOI_1, DOI_2, etc.
    # --------------------------------------------------------

    for column_name, col in header_map.items():

        if not isinstance(column_name, str):
            continue

        if not re.fullmatch(
                r"DOI_\d+",
                column_name
        ):
            continue

        for row in range(2, ws.max_row + 1):

            cell = ws.cell(
                row=row,
                column=col
            )

            if not cell.value:
                continue

            identifier = str(cell.value).strip()

            # Add a hyperlink only when the cell contains a DOI.
            # WOS UT fallback values remain plain text.
            if is_valid_doi(identifier):
                cell.hyperlink = (
                    f"https://doi.org/{identifier}"
                )

                cell.style = "Hyperlink"

wb.save(OUTPUT_XLSX)

# ============================================================
# 15. Export Article Titles and Abstracts
# ============================================================

with open(
        OUTPUT_TXT,
        "w",
        encoding="utf-8"
) as f:
    for ut, info in all_article_text.items():
        f.write(f"UT: {ut}\n")
        f.write(f"DOI: {ut_to_doi.get(ut, '')}\n")
        f.write(f"Title: {info.get('title', '')}\n")
        f.write(f"Abstract: {info.get('abstract', '')}\n")
        f.write("\n")
        f.write("=" * 100)
        f.write("\n\n")

