import os
from openai import OpenAI
from datetime import datetime
import json
import re
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from pathlib import Path

INDEX_FILE = "./File/Index.txt"
SMART_FILE = "./File/AOP-Smart.json"
API_CONFIG_FILE = Path("./API.json")

input_word = os.environ.get("INPUT_WORD", "").strip()

if not input_word:
    raise SystemExit("❌ No INPUT_WORD has been received. Please run it via bat or set it in the environment variables.")

BASE_DIR = Path(__file__).resolve().parent / "File"


def _load(name: str) -> str:
    return (BASE_DIR / name).read_text(encoding="utf-8")


PROMPT_TEMPLATES = {
    "screen_article": {
        "1": _load("screen_article1.txt"),
        "2": _load("screen_article2.txt"),
    },
    "get_id": {
        "1": _load("get_id1.txt"),
        "2": _load("get_id2.txt"),
    },
    "get_ker": {
        "1": _load("get_ker1.txt"),
        "2": _load("get_ker2.txt"),
    },
}


def render_prompt(prompt_type: str, prompt_version: str,
                  compound_desc: str, toxicity_focus: str = "") -> str:
    try:
        template = PROMPT_TEMPLATES[prompt_type][prompt_version]
    except KeyError:
        raise ValueError(
            f"Unknown prompt: type={prompt_type!r}, version={prompt_version!r}. "
            f"Available: { {k: list(v) for k, v in PROMPT_TEMPLATES.items()} }"
        ) from None

    return template.format(
        compound_desc=compound_desc,
        toxicity_focus=toxicity_focus,
    )


# API function
def _load_api_configs():
    """Load valid API configurations from API.json."""
    if not API_CONFIG_FILE.exists():
        return []

    try:
        with open(API_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[WARNING] Failed to read API.json: {exc}")
        return []

    if not isinstance(data, list):
        return []

    configs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        base_url = str(item.get("base_url", "")).strip()
        api_key = str(item.get("api_key", "")).strip()
        if base_url and api_key:
            configs.append({"base_url": base_url, "api_key": api_key})
    return configs


def _save_api_configs(configs):
    """Persist API configurations to API.json."""
    try:
        with open(API_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[WARNING] Failed to save API.json: {exc}")


def _mask_api_key(api_key):
    """Show only the first five characters of an API key."""
    return f"{api_key[:5]}***" if api_key else "***"


def resolve_llm_credentials():
    print("\n" + "=" * 80)
    print("[INPUT] Please configure your LLM API settings:")
    print("        (These credentials will be used to process and extract AOP data)")

    saved_configs = _load_api_configs()

    if saved_configs:
        print("\n[INFO] Saved API configuration(s) found in API.json:")
        for i, cfg in enumerate(saved_configs):
            print(f"  {i}: {cfg['base_url']}  (key: {_mask_api_key(cfg['api_key'])})")
        print(f"  {len(saved_configs)}: Enter a new configuration")

        while True:
            raw = input(
                f"  -> Select by index [0-{len(saved_configs)}], "
                f"or press Enter to add a new one: "
            ).strip()

            # Empty input = add new config
            if not raw:
                break

            if not raw.isdigit():
                print("     [ERROR] Please enter a valid number.")
                continue

            choice = int(raw)

            if 0 <= choice < len(saved_configs):
                cfg = saved_configs[choice]
                print(f"     [OK] Using saved config: {cfg['base_url']}")
                return cfg["base_url"], cfg["api_key"]

            if choice == len(saved_configs):
                break

            print(f"     [ERROR] Index out of range (0-{len(saved_configs)}).")

    print("\n[INPUT] Enter new API credentials:")

    while True:
        base_url = input("  -> Base URL (e.g., https://api.openai.com/v1): ").strip()
        if base_url:
            break
        print("     [ERROR] Base URL cannot be empty.")

    while True:
        api_key = input("  -> API KEY (Your secret key for the model provider): ").strip()
        if api_key:
            break
        print("     [ERROR] API KEY cannot be empty.")

    new_cfg = {"base_url": base_url, "api_key": api_key}

    if new_cfg in saved_configs:
        print("     [INFO] This configuration already exists in API.json.")
    else:
        saved_configs.append(new_cfg)
        _save_api_configs(saved_configs)
        print("     [OK] New configuration saved to API.json.")

    return base_url, api_key


def parse_llm_output(text):
    results = []
    lines = text.splitlines()

    for line in lines:
        line = line.strip()
        if not line.startswith("[") or not line.endswith("]"):
            continue

        content = line[1:-1]
        parts = content.split("|")

        if len(parts) != 3:
            continue

        results.append({
            "upevent": parts[0].strip(),
            "downevent": parts[1].strip(),
            "species": parts[2].strip()
        })

    return results


# --------------------------
# Step 0: Pre-screening
# --------------------------
def screen_article(client, model_name, temperature, title, abstract, compound_desc, toxicity_focus="",
                   prompt_version="1"):
    template = PROMPT_TEMPLATES["screen_article"].get(prompt_version)
    system_prompt = template.format(compound_desc=compound_desc, toxicity_focus=toxicity_focus, )
    user_content = f"Title: {title}\n\nAbstract: {abstract}"

    extra_kwargs = {}
    if "deepseek" in model_name.lower():
        extra_kwargs["reasoning_effort"] = "high"

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=temperature,
        max_tokens=10000,
        **extra_kwargs
    )

    raw = (response.choices[0].message.content or "").strip()
    low = raw.lower()
    keep = low.startswith("yes")
    return keep, raw


# --------------------------
# Step 1: KE selection
# --------------------------
def get_relevant_ke_ids(client, question, model_name, temperature, top_n, compound_desc, toxicity_focus, prompt_version="1"):
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_data = f.read()

    template = PROMPT_TEMPLATES["get_id"][prompt_version]
    system_prompt = template.format(
        compound_desc=compound_desc,
        toxicity_focus=toxicity_focus,
        top_n=top_n,
    )

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{index_data}\n\n<literature>\n{question}\n</literature>"}
        ],
        temperature=temperature,
        max_tokens=30000,
    )

    text = response.choices[0].message.content.strip()
    match = re.search(r"\[(.*?)\]", text)
    if match:
        ids = match.group(1).split(",")
        return [i.strip() for i in ids if i.strip()]

    return []


# --------------------------
# Context
# --------------------------
def simplify_context(selected_ke, selected_ker, selected_aop, kers, key_events):
    ke_entries = []
    for ke_id, ke in selected_ke.items():
        title = ke.get("title", "") or "-"
        level = ke.get("level", "") or "-"
        ke_entry = f"[{ke_id}|{title}|{level}]"
        ke_entries.append(ke_entry)
    ke_prompt = """Below is a list of Key Events (KE) in a simplified format.
Each KE is enclosed in square brackets [] with fields separated by '|':
[id | title | level ]
- id: Unique identifier of the KE (always present)
- title: Name of the KE (always present)
- level: Biological level (Molecular, Cellular, Tissue, Individual, etc.; use '-' if unknown)\n"""
    ke_text = "\n KE:\n" + "\n".join(ke_entries) + "\n"

    ker_entries = []
    for ker_id, ker in selected_ker.items():
        upstream = ker.get("upstream_id") or "-"
        downstream = ker.get("downstream_id") or "-"
        ker_entry = f"[{upstream}->{downstream}]"
        ker_entries.append(ker_entry)
    ker_prompt = """Below is a list of Key Event Relationships (KERs) in a simplified format.
Each KER is in its own square brackets [] in the following format:
[upstream_id -> downstream_id]
- upstream_id: KE ID of the upstream event 
- downstream_id: KE ID of the downstream event
"""
    ker_text = "\nKER:\n" + "\n".join(ker_entries)

    aop_entries = []
    for aop_id, aop in selected_aop.items():
        title = aop.get("title", "") or "-"

        def format_ke_list(ids):
            formatted = []
            for ke_id in ids:
                ke_id_str = str(ke_id)
                if ke_id_str in key_events:
                    title = key_events[ke_id_str].get("title", "")
                    formatted.append(f"{ke_id_str}({title})")
                else:
                    formatted.append(ke_id_str)
            return formatted

        mie_ids = format_ke_list([m.get("key_event_id", "-") for m in aop.get("MIEs", [])] or ["-"])
        ke_ids = format_ke_list(aop.get("KEs", []) or ["-"])
        ao_ids = format_ke_list([a.get("key_event_id", "-") for a in aop.get("AOs", [])] or ["-"])

        ker_rels = []
        for kr in aop.get("KE_relationships", []):
            upstream = kers[kr["id"]].get("upstream_id", "-") or "-"
            downstream = kers[kr["id"]].get("downstream_id", "-") or "-"
            ker_rels.append(f"{upstream}->{downstream}")
        if not ker_rels:
            ker_rels = ["-"]

        aop_entry = f"[{aop_id}|{title}|MIEs:{','.join(mie_ids)}|KEs:{','.join(ke_ids)}|AOs:{','.join(ao_ids)}|KERs:{','.join(ker_rels)}]"
        aop_entries.append(aop_entry)

    aop_prompt = """
    Below is a list of Adverse Outcome Pathways (AOPs) in simplified format.
    Each AOP is represented in square brackets [] with fields separated by '|':
    [id | title | MIEs | KEs | AOs | KERs]
    Definitions:
    - MIEs (Molecular Initiating Events): the starting KEs in the pathway (no upstream)
    - KEs: intermediate Key Events between MIEs and AOs
    - AOs (Adverse Outcomes): the ending KEs in the pathway (no downstream)
    - KERs: causal relationships in the format upstream_ke_id -> downstream_ke_id
    """
    aop_text = "AOP:\n" + "\n".join(aop_entries) + "\n"

    overall_prompt = """The following is an AOP knowledge base:\n
    """
    AOP_smart = overall_prompt + "<KE>\n" + ke_prompt + ke_text + "</KE>\n\n" + "<KE_relation>\n" + ker_prompt + ker_text + "\n</KE_relation>" + "\n\n<AOP>\n" + aop_prompt + aop_text + "</AOP>"

    return AOP_smart


# --------------------------
# Build context
# --------------------------
def build_context_from_ke_ids(ke_ids):
    with open(SMART_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    key_events = data["key_events"]
    kers = data["kers"]
    aops = data.get("aops", {})

    selected_ke = {}
    selected_ker = {}
    selected_aop = {}

    int_ke_ids = set(ke_ids)
    up_ke = set()
    down_ke = set()

    # Extend
    for ker in kers.values():
        if ker["upstream_id"] in int_ke_ids:
            down_ke.add(ker["downstream_id"])
        if ker["downstream_id"] in int_ke_ids:
            up_ke.add(ker["upstream_id"])

    expanded_ke = int_ke_ids.union(up_ke).union(down_ke)

    # KE
    for ke_id in expanded_ke:
        if ke_id in key_events:
            selected_ke[ke_id] = key_events[ke_id]

    # KER
    for ker_id, ker in kers.items():
        upstream = ker.get("upstream_id")
        downstream = ker.get("downstream_id")
        if upstream in expanded_ke and downstream in expanded_ke:
            selected_ker[ker_id] = ker

    for aop_id, aop in aops.items():
        check = 0
        for mie in aop.get("MIEs", []):
            if mie.get("key_event_id") in expanded_ke:
                check += 1
        for ke in aop.get("KEs", []):
            if ke in expanded_ke:
                check += 1
        for ao in aop.get("AOs", []):
            if ao.get("key_event_id") in expanded_ke:
                check += 1
        if check >= 2:
            selected_aop[aop_id] = aop

    context = simplify_context(selected_ke, selected_ker, selected_aop, kers, key_events)
    return context


def run_llm(client, model_name, context, question, max_tokens, temperature, compound_desc, toxicity_focus="", prompt_version="1"):
    template = PROMPT_TEMPLATES["get_ker"][prompt_version]
    system_prompt = template.format(
        compound_desc=compound_desc,
        toxicity_focus=toxicity_focus,
    )
    user_content = f"""<AOP_CONTEXT>
    {context}
    </AOP_CONTEXT>

    <LITERATURE>
    {question}
    </LITERATURE>"""

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )

    result = response.choices[0].message.content.strip()
    return result


def process_article(idx, art, client, model_name, temperature, max_tokens, top_n,
                    compound_desc, toxicity_focus, lock, output_data, skipped_data,
                    output_file, skipped_file, prompt_version):
    title = art.get("Article Title", "")
    abstract = art.get("Abstract", "")
    ut = art.get("UT", "")
    doi = art.get("DOI", "")
    question = f"{title}\n\n{abstract}"

    try:
        # ---------- Step 0: Pre-screening ----------
        keep, screen_answer = screen_article(
            client, model_name, temperature, title, abstract, compound_desc, toxicity_focus, prompt_version
        )
        if not keep:
            skipped_entry = {
                "index": idx,
                "Article Title": title,
                "Abstract": abstract,
                "UT": ut,
                "DOI": doi,
                "screen_answer": screen_answer
            }
            with lock:
                skipped_data.append(skipped_entry)
                with open(skipped_file, "w", encoding="utf-8") as f:
                    json.dump(skipped_data, f, ensure_ascii=False, indent=2)
            return

        # ---------- Step 1: KE selection ----------
        ke_ids = get_relevant_ke_ids(client, question, model_name, temperature, top_n, compound_desc, toxicity_focus,
                                     prompt_version)

        # ---------- Step 2: Build context ----------
        context = build_context_from_ke_ids(ke_ids)

        # ---------- Step 3: Extract causal pairs ----------
        result_text = run_llm(client, model_name, context, question, max_tokens,
                              temperature, compound_desc, toxicity_focus, prompt_version)

        if not result_text:
            print(f"literature {idx} error")
            parsed = []
        else:
            parsed = parse_llm_output(result_text)

        output_entry = {
            "index": idx,
            "Article Title": title,
            "Abstract": abstract,
            "UT": ut,
            "DOI": doi,
            "Events": parsed
        }

    except Exception as e:
        print(f"literature {idx} error: {e}")
        output_entry = {
            "index": idx,
            "Article Title": title,
            "Abstract": abstract,
            "UT": ut,
            "DOI": doi,
            "Events": [],
            "error": str(e)
        }

    # Thread-safe writing
    with lock:
        output_data.append(output_entry)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)


def load_json_safe(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# --------------------------
# Post-processing: unify candidate event names
# --------------------------

def extract_candidate_event_names(output_data):
    """Collect unique upevent/downevent names containing 'candidate'."""
    names = set()
    for item in output_data:
        for ev in item.get("Events") or []:
            if not isinstance(ev, dict):
                continue
            for field in ("upevent", "downevent"):
                name = (ev.get(field) or "").strip()
                if name and "candidate" in name.lower():
                    names.add(name)
    return sorted(names)


def _parse_unify_json(text):
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 提取第一个平衡的 {...}
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                chunk = re.sub(r",\s*([}\]])", r"\1", text[start:i + 1])
                try:
                    obj = json.loads(chunk)
                    return obj if isinstance(obj, dict) else {}
                except json.JSONDecodeError:
                    return {}
    return {}


def _build_mapping_from_groups(groups, input_set):
    mapping = {name: name for name in input_set}  # 默认自映射
    warnings = []
    seen_syn = {}

    for canonical, syns in groups.items():
        canonical = str(canonical).strip()
        if canonical not in input_set:
            warnings.append(f"Canonical not in input, skipped: {canonical!r}")
            continue
        if "candidate" not in canonical.lower():
            warnings.append(f"Canonical missing 'candidate', skipped: {canonical!r}")
            continue

        mapping[canonical] = canonical
        if not isinstance(syns, list):
            syns = [syns]

        for s in syns:
            s = str(s).strip()
            if not s:
                continue
            if s not in input_set:
                warnings.append(f"Synonym not in input, skipped: {s!r} (group {canonical!r})")
                continue
            if s in seen_syn and seen_syn[s] != canonical:
                warnings.append(
                    f"Synonym {s!r} in multiple groups: "
                    f"{seen_syn[s]!r} vs {canonical!r}; keeping first"
                )
                continue
            seen_syn[s] = canonical
            mapping[s] = canonical

    return mapping, warnings


def unify_candidate_events_with_llm(client, model_name, events, compound_desc):
    if not events:
        return {}
    s = {compound_desc}
    system_prompt = f"""
You are an expert in biomedical and toxicology terminology, familiar with Adverse Outcome Pathway (AOP) vocabulary.

Below is a list of biological event names automatically extracted from literature. 
Every name contains the token "candidate", meaning no exact match was found in the AOP-Wiki knowledge base.

Your task: identify groups of names that refer to the SAME biological event, and output ONLY those groups as a JSON object.
Rules:
1. Group names only if they refer to the same biological event. Semantically distinct events must stay separate 
(e.g., Apoptosis vs. Necrosis, Oxidative stress vs. Oxidative DNA damage).

2. For each group, pick one canonical name FROM THE GROUP'S OWN MEMBERS. The canonical name MUST contain "candidate".
3. Output ONLY groups that contain 2 or more semantically equivalent names. DO NOT output singleton groups. 
Names not included in any group will be treated as self-mappings.
4. Each name must appear in at most one group. Do not invent names not present in the input.
5. Output valid JSON only. No markdown fences, no explanations, no comments.

Output format:
{{
  "Canonical name 1(candidate)": ["Synonym A(candidate)", "Synonym B(candidate)"],
  "Canonical name 2(candidate)": ["Synonym C(candidate)", "Synonym D(candidate)"]
}}

Input event list:
"""

    user_prompt = system_prompt + "\n".join(events) + "\n\nOutput JSON:\n"

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a biomedical terminology expert. Output valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=50000,
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[WARNING] Candidate unification failed: {e}")
        return {}

    groups = _parse_unify_json(text)
    if not groups:
        print("[WARNING] No JSON object could be parsed from LLM output.")
        return {}

    covered = sum(len(v) if isinstance(v, list) else 1 for v in groups.values())
    print(f"[INFO] LLM returned {len(groups)} merge groups covering {covered} names.")

    mapping, warnings = _build_mapping_from_groups(groups, set(events))
    for w in warnings[:20]:
        print(f"[WARNING] {w}")
    if len(warnings) > 20:
        print(f"[WARNING] ... and {len(warnings) - 20} more warnings")

    return mapping


def apply_candidate_mapping(output_data, mapping):
    """Replace upevent/downevent using the mapping. Returns replacement count."""
    if not mapping:
        return 0

    replaced = 0
    for item in output_data:
        for ev in item.get("Events") or []:
            if not isinstance(ev, dict):
                continue
            for field in ("upevent", "downevent"):
                val = ev.get(field)
                if isinstance(val, str) and val in mapping:
                    new_val = mapping[val]
                    if new_val != val:
                        ev[field] = new_val
                        replaced += 1
    return replaced


def post_process_candidate_events(client, model_name, compound_desc, input_word,
                                  output_file, output_data, force=True):
    """Unify candidate event names in Finder.json and write back."""
    map_file = f"./{input_word}/candidate_unify_map.json"

    if not force and os.path.exists(map_file):
        print(f"[INFO] Candidate mapping already exists at {map_file}, skipping unification.")
        return output_data

    candidate_events = extract_candidate_event_names(output_data)
    if not candidate_events:
        print("[INFO] No candidate events found, skipping unification.")
        return output_data

    print(f"\n[INFO] Found {len(candidate_events)} unique candidate event names.")
    print("[INFO] Calling LLM to unify synonyms (single call, group-JSON mode)...")

    mapping = unify_candidate_events_with_llm(
        client, model_name, candidate_events, compound_desc
    )

    with open(map_file, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Candidate mapping saved to {map_file} ({len(mapping)} entries)")

    replaced = apply_candidate_mapping(output_data, mapping)
    print(f"[INFO] Replaced {replaced} event name occurrences in Finder.json.")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    remaining = extract_candidate_event_names(output_data)
    print(f"[INFO] Unique candidate event names: {len(candidate_events)} -> {len(remaining)}")

    return output_data


def main():
    print("=== AOP-Smart-Finder ===")

    with open(SMART_FILE, "r", encoding="utf-8") as f:
        smart_data = json.load(f)
        xml_version = smart_data.get("metadata", {}).get("xml_version", "Unknown")
        print(f"[INFO] Knowledge Base AOP-Wiki_XML Version: {xml_version}")

    print("\n" + "=" * 80)
    print("[NOTICE] If you need to update the knowledge base version:")
    print("         1. Delete all files in the 'File' folder.")
    print("         2. Rename the newly downloaded XML file to 'aop-wiki.xml'.")
    print("         3. Place it into the 'File' folder.")
    print("         4. Restart the current BAT program.")
    print("=" * 80 + "\n")

    temperature = 0
    max_tokens = 20000
    top_n = 10
    while not (s := input("Max threads (default 20): ").strip()).isdigit() and s: print("Please enter a number")
    max_threads = int(s) if s else 20

    base_url, api_key = resolve_llm_credentials()
    compound_desc = input_word
    client = OpenAI(api_key=api_key, base_url=base_url)

    models = client.models.list()
    model_list = [m.id for m in models.data]

    print("\nAvailable Models:")
    for i, m in enumerate(model_list):
        print(f"  {i}: {m}")

    model_name = model_list[int(input("  -> Select model by index: "))]
    print("\n" + "-" * 80)
    print("[OPTIONAL] Extraction Guidance:")
    print("        (Provide a sentence or a paragraph to guide the LLM to focus on")
    print("         specific toxicities, mechanisms, target organs, etc.)")
    print("        (If left blank, it will extract all KERs of the target compound by default.)")
    toxicity_focus = input("  -> Enter your guidance: ").strip()

    print("\n[OPTIONAL] Prompt Version:")
    print("        1 = Single-compound mode (only compound-alone exposure evidence is used)")
    print("        2 = No-compound-restriction mode")
    while True:
        prompt_version = input("  -> Select prompt version (1/2, default 1): ").strip() or "1"
        if prompt_version in ("1", "2"):
            break
        print("     Invalid input, please enter 1 or 2.")

    print("=" * 80 + "\n")
    with open(f"./{input_word}/wos_articles.json", "r", encoding="utf-8") as f:
        articles = json.load(f)

    output_file = f"./{input_word}/Finder.json"
    skipped_file = f"./{input_word}/Finder_skipped.json"

    output_data = load_json_safe(output_file)
    skipped_data = load_json_safe(skipped_file)
    done_uts = set()
    done_indexes = set()

    for item in output_data + skipped_data:
        ut = item.get("UT", "")
        if ut:
            done_uts.add(ut)
        idx = item.get("index")
        if idx is not None:
            done_indexes.add(idx)

    articles_to_run = []
    for idx, art in enumerate(articles):
        ut = art.get("UT", "")
        if ut and ut in done_uts:
            continue
        if idx in done_indexes:
            continue
        articles_to_run.append((idx, art))

    print(f"\nTotal articles: {len(articles)}")
    print(f"Already processed: {len(articles) - len(articles_to_run)}")
    print(f"To run: {len(articles_to_run)}")

    if not articles_to_run:
        print("All articles already processed. Nothing to do.")
        post_process_candidate_events(
            client, model_name, compound_desc, input_word,
            output_file, output_data, force=False
        )
        return

    lock = Lock()
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [
            executor.submit(process_article, idx, art, client, model_name, temperature,
                            max_tokens, top_n, compound_desc, toxicity_focus, lock,
                            output_data, skipped_data, output_file, skipped_file, prompt_version)
            for idx, art in articles_to_run
        ]

        for i, future in enumerate(as_completed(futures), 1):
            print(f"{i}/{len(futures)} tasks done")

    output_data.sort(key=lambda x: x["index"])
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    skipped_data.sort(key=lambda x: x["index"])
    with open(skipped_file, "w", encoding="utf-8") as f:
        json.dump(skipped_data, f, ensure_ascii=False, indent=2)

    # ---------- Post-process: unify candidate event names ----------
    output_data = post_process_candidate_events(
        client, model_name, compound_desc, input_word,
        output_file, output_data, force=True
    )

    print(f"\n Done! Kept {len(output_data)}, Skipped {len(skipped_data)}")
    print()


if __name__ == "__main__":
    main()
