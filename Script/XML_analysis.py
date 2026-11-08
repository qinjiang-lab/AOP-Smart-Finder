from lxml import etree
import json
import re
import hashlib

# -----------------------------
# Config
# -----------------------------
xml_file = "./File/aop-wiki.xml"
output_json = "./File/AOP-Smart.json"

ns = {"aopns": "http://www.aopkb.org/aop-xml"}


# AOP-Wiki_XML Version
def get_xml_version(xml_file):
    for _, elem in etree.iterparse(
            xml_file,
            events=("end",),
            tag="{http://www.aopkb.org/aop-xml}vendor-specific"
    ):
        version = elem.get("version")
        elem.clear()
        return version

    return None


# Hash
def get_file_md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


# -----------------------------
# Text cleaning
# -----------------------------
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<.*?>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# -----------------------------
# Build the mapping
# -----------------------------
def build_reference_maps(xml_file):
    aop_map = {}
    ke_map = {}
    ker_map = {}
    taxonomy_map = {}
    context = etree.iterparse(xml_file, events=("end",), tag=None)
    context2 = etree.iterparse(xml_file, events=("end",), tag="{http://www.aopkb.org/aop-xml}taxonomy")
    for _, elem in context2:
        parent_tag = etree.QName(elem.getparent()).localname if elem.getparent() is not None else ''
        if parent_tag == 'data':
            name = elem.findtext("aopns:name", "", namespaces=ns)
            tax_id = elem.get('id')
            taxonomy_map[tax_id] = name

    for _, elem in context:
        tag = etree.QName(elem.tag).localname

        if tag == "aop-reference":
            uuid = elem.get("id")
            real_id = elem.get("aop-wiki-id")
            if uuid and real_id:
                aop_map[uuid] = f"{real_id}"

        elif tag == "key-event-reference":
            uuid = elem.get("id")
            real_id = elem.get("aop-wiki-id")
            if uuid and real_id:
                ke_map[uuid] = real_id

        elif tag == "key-event-relationship-reference":
            uuid = elem.get("id")
            real_id = elem.get("aop-wiki-id")
            if uuid and real_id:
                ker_map[uuid] = real_id
        elem.clear()

    print(f"AOP_ID mapping: {len(aop_map)}")
    print(f"KE_ID mapping: {len(ke_map)}")
    print(f"KER_ID mapping: {len(ker_map)}")
    print(f"Taxonomy_ID mapping: {len(taxonomy_map)}")
    return aop_map, ke_map, ker_map, taxonomy_map


# -----------------------------
#  Analysis KE
# -----------------------------
def parse_key_events(xml_file, ke_map, taxonomy_map):
    ke_dict = {}

    context = etree.iterparse(xml_file, events=("end",), tag="{http://www.aopkb.org/aop-xml}key-event")
    for _, elem in context:
        ke_id = elem.get("id")
        if not ke_id:
            elem.clear()
            continue
        ke_id_real = ke_map.get(ke_id, ke_id)

        ke_dict[ke_id_real] = {
            "title": clean_text(elem.findtext("aopns:title", "", ns)),
            "short_name": clean_text(elem.findtext("aopns:short-name", "", ns)),
            "level": clean_text(elem.findtext("aopns:biological-organization-level", "", ns)),
            "organ": clean_text(elem.findtext("aopns:organ-term/aopns:name", "", ns)),
            "cell": clean_text(elem.findtext("aopns:cell-term/aopns:name", "", ns)),
            "description": clean_text(elem.findtext("aopns:description", "", ns)),
            "applicability": {
                "sex": [],
                "life_stage": [],
                "taxonomy": []
            }
        }
        # applicability
        for sex in elem.findall("aopns:applicability/aopns:sex", ns):
            ke_dict[ke_id_real]["applicability"]["sex"].append({
                "sex": clean_text(sex.findtext("aopns:sex", "", ns)),
                "evidence": clean_text(sex.findtext("aopns:evidence", "", ns))
            })
        for ls in elem.findall("aopns:applicability/aopns:life-stage", ns):
            ke_dict[ke_id_real]["applicability"]["life_stage"].append({
                "life_stage": clean_text(ls.findtext("aopns:life-stage", "", ns)),
                "evidence": clean_text(ls.findtext("aopns:evidence", "", ns))
            })
        for tax in elem.findall("aopns:applicability/aopns:taxonomy", ns):
            tax_id = tax.get("taxonomy-id")
            tax_name = taxonomy_map.get(tax_id, tax_id)
            ke_dict[ke_id_real]["applicability"]["taxonomy"].append({
                "taxonomy": tax_name,
                "evidence": clean_text(tax.findtext("aopns:evidence", "", ns))
            })
        elem.clear()

    print(f"KE count: {len(ke_dict)}")
    return ke_dict


# -----------------------------
# Analysis AOP
# -----------------------------
def parse_aops(xml_file, aop_map, ke_map, ker_map, taxonomy_map):
    aop_dict = {}

    context = etree.iterparse(xml_file, events=("end",), tag="{http://www.aopkb.org/aop-xml}aop")
    for _, elem in context:
        aop_id = elem.get("id")
        if not aop_id:
            elem.clear()
            continue
        aop_id_real = aop_map.get(aop_id, aop_id)

        aop_entry = {
            "title": clean_text(elem.findtext("aopns:title", "", ns)),
            "abstract": clean_text(elem.findtext("aopns:abstract", "", ns)),
            "creation_time": clean_text(elem.findtext("aopns:creation-timestamp", "", ns)),
            "last_modified": clean_text(elem.findtext("aopns:last-modification-timestamp", "", ns)),
            "MIEs": [],
            "KEs": [],
            "AOs": [],
            "KE_relationships": [],
            "applicability": {
                "sex": [],
                "life_stage": [],
                "taxonomy": []
            }
        }

        # MIE
        for mie in elem.findall("aopns:molecular-initiating-event", ns):
            ke_ref = mie.get("key-event-id")
            aop_entry["MIEs"].append({
                "key_event_id": ke_map.get(ke_ref, ke_ref),
                "evidence_supporting_chemical_initiation": clean_text(
                    mie.findtext("aopns:evidence-supporting-chemical-initiation", "", ns))
            })

        # KEs
        for ke in elem.findall("aopns:key-events/aopns:key-event", ns):
            ke_ref = ke.get("key-event-id")
            aop_entry["KEs"].append(ke_map.get(ke_ref, ke_ref))

        # AO
        for ao in elem.findall("aopns:adverse-outcome", ns):
            ke_ref = ao.get("key-event-id")
            aop_entry["AOs"].append({
                "key_event_id": ke_map.get(ke_ref, ke_ref),
                "examples": clean_text(ao.findtext("aopns:examples", "", ns))
            })

        # KE relationships
        for ker in elem.findall("aopns:key-event-relationships/aopns:relationship", ns):
            ker_ref = ker.get("id")
            aop_entry["KE_relationships"].append({
                "id": ker_map.get(ker_ref, ker_ref),
                "adjacency": clean_text(ker.findtext("aopns:adjacency", "", ns)),
                "quantitative_understanding_value": clean_text(
                    ker.findtext("aopns:quantitative-understanding-value", "", ns)),
                "evidence": clean_text(ker.findtext("aopns:evidence", "", ns))
            })

        # applicability
        for sex in elem.findall("aopns:applicability/aopns:sex", ns):
            aop_entry["applicability"]["sex"].append({
                "sex": clean_text(sex.findtext("aopns:sex", "", ns)),
                "evidence": clean_text(sex.findtext("aopns:evidence", "", ns))
            })
        for ls in elem.findall("aopns:applicability/aopns:life-stage", ns):
            aop_entry["applicability"]["life_stage"].append({
                "life_stage": clean_text(ls.findtext("aopns:life-stage", "", ns)),
                "evidence": clean_text(ls.findtext("aopns:evidence", "", ns))
            })
        for tax in elem.findall("aopns:applicability/aopns:taxonomy", ns):
            tax_id = tax.get("taxonomy-id")
            tax_name = taxonomy_map.get(tax_id, tax_id)
            aop_entry["applicability"]["taxonomy"].append({
                "taxonomy": tax_name,
                "evidence": clean_text(tax.findtext("aopns:evidence", "", ns))
            })

        aop_dict[aop_id_real] = aop_entry
        elem.clear()

    print(f"AOP count: {len(aop_dict)}")
    return aop_dict


#  Analysis KER
def parse_kers(xml_file, ke_map, ker_map, taxonomy_map):
    ker_dict = {}
    ns = {"aopns": "http://www.aopkb.org/aop-xml"}
    context = etree.iterparse(xml_file, events=("end",), tag="{http://www.aopkb.org/aop-xml}key-event-relationship")

    for _, elem in context:
        ker_id = elem.get("id")
        if not ker_id:
            elem.clear()
            continue

        ker_id_real = ker_map.get(ker_id, ker_id)  # 映射 KER ID

        upstream_id = elem.findtext("aopns:title/aopns:upstream-id", "", ns)
        downstream_id = elem.findtext("aopns:title/aopns:downstream-id", "", ns)
        description = clean_text(elem.findtext("aopns:description", "", ns))

        applicability = {"sex": [], "life_stage": [], "taxonomy": []}
        app_elem = elem.find("aopns:applicability", ns)
        if app_elem is not None:
            for sex in app_elem.findall("aopns:sex", ns):
                applicability["sex"].append({
                    "sex": clean_text(sex.findtext("aopns:sex", "", ns)),
                    "evidence": clean_text(sex.findtext("aopns:evidence", "", ns))
                })
            for ls in app_elem.findall("aopns:life-stage", ns):
                applicability["life_stage"].append({
                    "life_stage": clean_text(ls.findtext("aopns:life-stage", "", ns)),
                    "evidence": clean_text(ls.findtext("aopns:evidence", "", ns))
                })
            for tax in app_elem.findall("aopns:taxonomy", ns):
                tax_id = tax.get("taxonomy-id")
                tax_name = taxonomy_map.get(tax_id, tax_id)
                applicability["taxonomy"].append({
                    "taxonomy": tax_name,
                    "evidence": clean_text(tax.findtext("aopns:evidence", "", ns))
                })

        ker_dict[ker_id_real] = {
            "upstream_id": ke_map.get(upstream_id, upstream_id),  # 映射 upstream KE
            "downstream_id": ke_map.get(downstream_id, downstream_id),  # 映射 downstream KE
            "description": description,
            "applicability": applicability
        }
        elem.clear()

    print(f"KER count: {len(ker_dict)}")
    return ker_dict


# -----------------------------
# main process
# -----------------------------
def main():
    print("Step 1: Build the ID mapping...")
    aop_map, ke_map, ker_map, taxonomy_map = build_reference_maps(xml_file)

    print("Step 2: Analysis KE...")
    ke_data = parse_key_events(xml_file, ke_map, taxonomy_map)

    print("Step 3: Analysis AOP...")
    aop_data = parse_aops(xml_file, aop_map, ke_map, ker_map, taxonomy_map)

    print("Step 4: Analysis KER...")
    ker_data = parse_kers(xml_file, ke_map, ker_map, taxonomy_map)

    print("Step 5:Version...")
    version = get_xml_version(xml_file)
    # 输出 JSON
    output = {
        "metadata": {
            "xml_version": version.split(" ")[0],
            "file_md5": get_file_md5(xml_file)
        },
        "key_events": ke_data,
        "kers": ker_data,
        "aops": aop_data
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Done! Output file: {output_json}")


def index():
    input_json = "./File/AOP-Smart.json"
    output_txt = "./File/Index.txt"

    prompt = """
    """

    # -----------------------------
    # Read the JSON file
    # -----------------------------
    with open(input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    key_events = data.get("key_events", {})

    # -----------------------------
    # Write to TXT file
    # -----------------------------
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(prompt + "\n")
        for ke_id, ke_info in key_events.items():
            line = f"{ke_id}|{ke_info.get('title', '')}"
            f.write(line + "\n")

    print(f"Done! Total KE count: {len(key_events)}")
    print(f"Saved as: {output_txt}")


if __name__ == "__main__":
    main()
    index()
