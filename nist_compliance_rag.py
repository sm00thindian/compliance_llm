import argparse
import configparser
import hashlib
import io
import json
import logging
import os
import re
import requests
import sys
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import pandas as pd
import pickle
from tqdm import tqdm
import xml.etree.ElementTree as ET
import glob
from colorama import init, Fore, Style
import spacy

# Load spaCy model
nlp = spacy.load('en_core_web_sm')

# Initialize colorama for cross-platform colored terminal output
init()

# Ensure the 'knowledge' sub-folder exists
KNOWLEDGE_DIR = 'knowledge'
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

# Configure logging to debug.log file in the 'knowledge' folder
logging.basicConfig(
    filename=os.path.join(KNOWLEDGE_DIR, 'debug.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)

def normalize_control_id(control_id):
    """Normalize control IDs by removing leading zeros and ensuring proper format."""
    match = re.match(r'^([A-Z]{2})-0*([0-9]+)(?:\(([a-z0-9]+)\))?$', control_id)
    if match:
        family, number, enhancement = match.groups()
        return f"{family}-{number}" + (f"({enhancement})" if enhancement else "")
    return control_id

def fetch_json_data(url):
    """Fetch JSON data from a URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Fetched data from {url}")
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch JSON data from {url}: {e}")
        return None

def fetch_excel_data(url, local_path):
    """Fetch Excel data from a URL if not already present locally."""
    if os.path.exists(local_path):
        logging.info(f"Using existing Excel file at {local_path}")
        with open(local_path, 'rb') as f:
            return io.BytesIO(f.read())
    else:
        try:
            response = requests.get(url)
            response.raise_for_status()
            with open(local_path, 'wb') as f:
                f.write(response.content)
            logging.info(f"Downloaded Excel data from {url} to {local_path}")
            return io.BytesIO(response.content)
        except requests.RequestException as e:
            logging.error(f"Failed to fetch Excel data from {url}: {e}")
            return None

def extract_controls_from_excel(excel_file):
    """Extract controls from NIST 800-53 Rev 5 Excel file."""
    controls = []
    df = pd.read_excel(excel_file, sheet_name='SP 800-53 Revision 5', header=None, skiprows=1)
    for _, row in df.iterrows():
        control_id = str(row[0]).upper()
        if not re.match(r'[A-Z]{2}-[0-9]+', control_id):
            continue
        title = str(row[1])
        description = str(row[2])
        related_controls = str(row[4]).split(', ') if pd.notna(row[4]) else []
        related_controls = [normalize_control_id(ctrl.upper()) for ctrl in related_controls if ctrl.strip()]
        controls.append({
            'control_id': control_id,
            'title': title,
            'description': description,
            'parameters': [],
            'related_controls': related_controls
        })
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 Excel catalog.")
    return controls

def extract_controls_from_json(json_data):
    """Extract controls from NIST 800-53 OSCAL JSON with descriptions and related controls."""
    controls = []
    if not json_data or 'catalog' not in json_data:
        logging.error("Invalid JSON structure: 'catalog' key missing.")
        return controls
    for group in json_data['catalog'].get('groups', []):
        for control in group.get('controls', []):
            control_id = control.get('id', '').upper()
            title = control.get('title', '')
            params = control.get('parameters', []) or []
            param_texts = [f"{param.get('id', '')}: {param.get('label', '')}" for param in params]
            description = " ".join(re.sub(r'\s+', ' ', part["prose"]).strip() for part in control.get('parts', []) if "prose" in part)
            related_controls = [link['href'].split('#')[-1].upper() for link in control.get('links', []) if link.get('rel') == 'related']
            controls.append({
                'control_id': control_id,
                'title': title,
                'description': description,
                'parameters': param_texts,
                'related_controls': related_controls
            })
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 JSON catalog.")
    return controls

def extract_assessment_procedures(json_data):
    """Extract assessment procedures from NIST SP 800-53A JSON."""
    assessments = {}
    if not json_data or 'assessment-plan' not in json_data:
        logging.error("Invalid JSON structure for 800-53A: 'assessment-plan' key missing.")
        return assessments
    for objective in json_data['assessment-plan'].get('objectives-and-methods', []):
        control_id = objective.get('target-id', '').upper()
        if control_id:
            methods = [m.get('description', '') for m in objective.get('assessment-methods', [])]
            assessments[control_id] = methods
    logging.info(f"Loaded {len(assessments)} assessment procedures from NIST SP 800-53A.")
    return assessments

def extract_high_baseline_controls(json_data):
    """Extract controls from NIST 800-53 High baseline JSON."""
    controls = []
    if not json_data or 'profile' not in json_data:
        logging.error("Invalid JSON structure: 'profile' key missing.")
        return controls
    for import_ in json_data['profile'].get('imports', []):
        for include in import_.get('include-controls', []):
            control_id = include.get('with-ids', [''])[0].upper()
            if control_id:
                controls.append(f"NIST 800-53 Rev 5 High Baseline, {control_id}: Included in High baseline.")
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 High baseline.")
    return controls

def load_cci_mapping(cci_xml_path):
    cci_to_nist = {}
    ns = {'cci': 'http://iase.disa.mil/cci'}  # Namespace for CCI XML
    try:
        tree = ET.parse(cci_xml_path)
        root = tree.getroot()
        for cci_item in root.findall('.//cci:cci_item', ns):
            cci_id = cci_item.get('id')
            rev5_control = None
            for ref in cci_item.findall('.//cci:reference', ns):
                ref_title = ref.get('title')
                ref_index = ref.get('index')
                if ref_title == 'NIST SP 800-53 Revision 5':
                    rev5_control = ref_index
                    break
            if rev5_control:
                cci_to_nist[cci_id] = rev5_control
        logging.info(f"Loaded {len(cci_to_nist)} CCI-to-NIST mappings from XML")
    except Exception as e:
        logging.error(f"Failed to parse CCI XML: {e}")
        cci_to_nist = {
            'CCI-000196': 'IA-5',
            'CCI-000048': 'AC-7',
            'CCI-002450': 'SC-13',
            'CCI-000130': 'AU-3',
            'CCI-000366': 'CM-6',
            'CCI-001764': 'CM-7 (5)'
        }
        logging.warning("Falling back to hardcoded CCI-to-NIST dictionary")
    return cci_to_nist

def parse_stig_xccdf(xccdf_data, cci_to_nist):
    """Parse STIG XCCDF file to extract rules and map to NIST controls via CCI."""
    try:
        root = ET.fromstring(xccdf_data)
        ns = {'xccdf': root.tag.split('}')[0][1:]}
        logging.info(f"Using namespace: {ns['xccdf']}")
        
        title_elem = root.find('.//xccdf:title', ns)
        title = title_elem.text if title_elem is not None else "Untitled STIG"
        
        title_lower = title.lower()
        if "windows 10" in title_lower:
            technology = "Windows 10"
        elif "red hat enterprise linux 9" in title_lower:
            technology = "Red Hat 9"
        else:
            technology = title.split(' ')[0]
        
        benchmark_id = root.get('id', 'Unknown')
        version_elem = root.find('.//xccdf:version', ns)
        version = version_elem.text if version_elem is not None else "Unknown"
        
        fixtexts = {fix.get('fixref'): fix.text for fix in root.findall('.//xccdf:fixtext', ns) if fix.text}
        
        stig_recommendations = {}
        rules = root.findall('.//xccdf:Rule', ns)
        logging.info(f"Found {len(rules)} rules in STIG")
        
        for rule in rules:
            rule_id = rule.get('id')
            title_elem = rule.find('.//xccdf:title', ns)
            title_text = title_elem.text if title_elem is not None else "No title"
            fix_elem = rule.find('.//xccdf:fix', ns)
            fix_ref = fix_elem.get('id') if fix_elem is not None else None
            fix_text = fixtexts.get(fix_ref, "No fix instructions provided.") if fix_ref else "No fix instructions provided."
            
            ccis = rule.findall('.//xccdf:ident[@system="http://cyber.mil/cci"]', ns)
            for cci in ccis:
                cci_id = cci.text
                control_id = cci_to_nist.get(cci_id)
                if control_id:
                    if control_id not in stig_recommendations:
                        stig_recommendations[control_id] = []
                    if not any(rec['rule_id'] == rule_id for rec in stig_recommendations[control_id]):
                        stig_recommendations[control_id].append({
                            'rule_id': rule_id,
                            'title': title_text,
                            'fix': fix_text
                        })
                    logging.debug(f"Mapped {cci_id} to {control_id} for rule {rule_id}")
        
        logging.info(f"Parsed STIG data for {technology}: {len(stig_recommendations)} controls mapped")
        return stig_recommendations, technology, title, benchmark_id, version
    except Exception as e:
        logging.error(f"Failed to parse STIG XCCDF: {e}")
        raise

def load_stig_data(stig_folder, cci_to_nist):
    """Load STIG data from XCCDF files in the specified folder."""
    all_stig_recommendations = {}
    available_stigs = []
    stig_files = glob.glob(os.path.join(stig_folder, '*.xml'))
    logging.info(f"Found {len(stig_files)} STIG files in {stig_folder}")
    
    for stig_file in stig_files:
        try:
            with open(stig_file, 'rb') as f:
                xccdf_data = f.read()
            recommendations, technology, title, benchmark_id, version = parse_stig_xccdf(xccdf_data, cci_to_nist)
            all_stig_recommendations[technology] = recommendations
            available_stigs.append({
                'file': os.path.basename(stig_file),
                'title': title,
                'technology': technology,
                'benchmark_id': benchmark_id,
                'version': version
            })
            logging.info(f"Successfully loaded STIG: {os.path.basename(stig_file)}")
        except Exception as e:
            logging.error(f"Failed to load STIG file '{stig_file}': {e}")
    logging.info(f"Loaded STIG recommendations for {len(all_stig_recommendations)} technologies.")
    return all_stig_recommendations, available_stigs

def extract_actionable_steps(description):
    """Extract actionable steps from a description using spaCy."""
    doc = nlp(description.lower())
    steps = []
    action_verbs = {'verify', 'ensure', 'check', 'review', 'confirm', 'examine'}
    
    for token in doc:
        if token.text in action_verbs and token.pos_ == 'VERB':
            for child in token.children:
                if child.dep_ in ('dobj', 'attr', 'prep') or child.pos_ in ('NOUN', 'PROPN'):
                    steps.append(f"{token.text} {child.text}")
                    break
            else:
                for next_token in doc[token.i + 1:]:
                    if next_token.pos_ in ('NOUN', 'PROPN'):
                        steps.append(f"{token.text} {next_token.text}")
                        break
                    elif next_token.text == '.':
                        break
    return steps if steps else [f"verify {doc.text.split('.')[0]}"]

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures):
    """Generate a user-friendly response to a query about NIST 800-53 controls, STIGs, or assessments."""
    query_lower = query.lower()
    response = []

    if "list stigs" not in query_lower:
        response.append(f"{Fore.YELLOW}**Answering:** '{query}'{Style.RESET_ALL}")
        response.append(f"Here’s what I found based on NIST 800-53 and available STIGs:\n")

    if "list stigs" in query_lower:
        keyword = query_lower.split("for")[1].strip() if "for" in query_lower else None
        filtered_stigs = [
            stig for stig in available_stigs 
            if not keyword or keyword.lower() in stig['technology'].lower() or keyword.lower() in stig['title'].lower()
        ]
        if not filtered_stigs:
            return f"No STIGs found{' for ' + keyword if keyword else ''}. Please check the `stig_folder` in `config.ini`."
        
        response.append(f"{Fore.CYAN}### Available STIGs{Style.RESET_ALL}")
        response.append("Here’s a list of STIGs loaded in the system:\n")
        response.append("+------------------------------------+----------------------+--------------+---------+")
        response.append("| File Name                          | Title                | Technology   | Version |")
        response.append("+------------------------------------+----------------------+--------------+---------+")
        for stig in filtered_stigs:
            short_title = stig['technology'] + " STIG"
            response.append(f"| {stig['file']:<34} | {short_title:<20} | {stig['technology']:<12} | {stig['version']:<7} |")
            response.append("+------------------------------------+----------------------+--------------+---------+")
        return "\n".join(response)

    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2}(?:\s*\([a-zA-Z0-9]+\))?)\b')
    control_ids = [match.replace(' ', '') for match in control_pattern.findall(query.upper())]
    system_match = re.search(r'for\s+([Windows|Linux|Red Hat|Ubuntu|macOS|Cisco].*?)(?:\s|$)', query, re.IGNORECASE)
    system_type = system_match.group(1).strip().rstrip('?') if system_match else None

    if control_ids:
        response.append(f"{Fore.YELLOW}**Controls Covered:** {', '.join(control_ids)}{Style.RESET_ALL}" + (f" for {system_type}" if system_type else ""))
    else:
        response.append(f"{Fore.RED}**No NIST controls detected.**{Style.RESET_ALL} Try including a control ID like 'AU-3'.")
        return "\n\n".join(response)

    is_assessment_query = "assess" in query_lower or "audit" in query_lower
    for control_id in control_ids:
        if control_id not in control_details:
            response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
            response.append(f"- **Status:** Not found in the catalog.")
            continue

        ctrl = control_details[control_id]
        response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
        response.append(f"- **Title:** {ctrl['title']}")
        response.append(f"- **Description:** {ctrl['description']}")

        if is_assessment_query:
            response.append(f"\n{Fore.CYAN}#### How to Assess {control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            if control_id in assessment_procedures:
                response.append(f"- **NIST SP 800-53A Assessment Steps:**")
                response.extend(f"  - {method}" for method in assessment_procedures[control_id])
            else:
                assess_docs = [doc.split(': ', 1)[1] for doc in retrieved_docs if f"Assessment, {control_id}" in doc]
                response.append(f"- **Steps to Verify:**")
                if assess_docs:
                    response.extend(f"  - {doc}" for doc in assess_docs)
                else:
                    actionable_steps = extract_actionable_steps(ctrl['description'])
                    response.extend(f"  - {step}" for step in actionable_steps)
                    if ctrl['parameters']:
                        response.append(f"  - Check parameters: {', '.join(ctrl['parameters'])}")

            stig_found = False
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type and system_type.lower() not in tech_lower:
                    continue
                if control_id in recs:
                    response.append(f"\n{Fore.CYAN}#### STIG-Based Assessment for {tech}{Style.RESET_ALL}")
                    for rec in recs[control_id]:
                        response.append(f"- **Rule {rec['rule_id']} - {rec['title']}**")
                        response.append(f"  - {Fore.GREEN}**Check:**{Style.RESET_ALL} Verify the fix is applied: {rec['fix']}")
                    stig_found = True
            if not stig_found and system_type:
                response.append(f"- No STIG assessment guidance found for {system_type}.")
            response.append(f"\n**More Info:** [NIST 800-53 Assessment Procedures](https://csrc.nist.gov/projects/risk-management/sp800-53-controls/assessment-procedures)")
        else:
            response.append(f"- **Parameters:** {', '.join(ctrl['parameters']) if ctrl['parameters'] else 'None specified'}")
            response.append(f"- **Related Controls:** {', '.join(ctrl['related_controls']) if ctrl['related_controls'] else 'None'}")
            if control_id in high_baseline_controls:
                response.append(f"- **Baseline:** Included in the High baseline")
            response.append(f"\n**Learn More:** [NIST 800-53 Catalog](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)")

        if "implement" in query_lower:
            response.append(f"\n{Fore.CYAN}### Implementation Guidance for {Fore.YELLOW}{control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            guidance = [doc.split(': ', 1)[1] for doc in retrieved_docs if control_id in doc and "Assessment" not in doc]
            response.append(f"{Fore.CYAN}#### NIST Guidance{Style.RESET_ALL}")
            if guidance:
                response.extend(f"- {g}" for g in guidance)
            else:
                response.append("- No specific NIST guidance found.")
            stig_found = False
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type and system_type.lower() not in tech_lower:
                    continue
                if control_id in recs:
                    response.append(f"{Fore.CYAN}#### STIG Recommendations for {tech}{Style.RESET_ALL}")
                    for rec in recs[control_id]:
                        short_title = rec['title'].split(' - ')[0][:50] + "..." if len(rec['title']) > 50 else rec['title']
                        response.append(f"- **{Fore.YELLOW}{short_title}{Style.RESET_ALL}** (Rule {rec['rule_id']})")
                        response.append(f"  - {Fore.GREEN}**Fix:**{Style.RESET_ALL} {rec['fix']}")
                    stig_found = True
            if not stig_found:
                response.append(f"{Fore.CYAN}#### STIG Recommendations{Style.RESET_ALL}")
                response.append(f"- No STIGs found for this control{' on ' + system_type if system_type else ''}.")

    if len(response) <= 2:
        response.append(f"{Fore.RED}**No detailed information available.**{Style.RESET_ALL}")
        response.append(f"Try rephrasing your query or visit [nist.gov](https://www.nist.gov).")

    return "\n\n".join(response)

def build_vector_store(documents, model_name):
    """Build or load a FAISS vector store from documents in the 'knowledge' folder."""
    index_file = os.path.join(KNOWLEDGE_DIR, f"faiss_index_{hashlib.md5(model_name.encode()).hexdigest()}.pkl")
    model = SentenceTransformer(model_name)
    logging.info(f"Load pretrained SentenceTransformer: {model_name}")
    
    if os.path.exists(index_file):
        with open(index_file, 'rb') as f:
            index, doc_list = pickle.load(f)
        logging.info(f"Loaded existing FAISS index from {index_file}")
    else:
        embeddings = model.encode(documents, show_progress_bar=True)
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings)
        doc_list = documents
        with open(index_file, 'wb') as f:
            pickle.dump((index, doc_list), f)
        logging.info(f"Built new FAISS index and saved to {index_file}")
    return model, index, doc_list

def retrieve_documents(query, model, index, doc_list, top_k=100):
    """Retrieve top-k relevant documents for a query."""
    query_embedding = model.encode([query])
    distances, indices = index.search(query_embedding, top_k)
    retrieved_docs = [doc_list[idx] for idx in indices[0]]
    logging.info(f"Retrieved {len(retrieved_docs)} documents for query")
    return retrieved_docs

def main():
    parser = argparse.ArgumentParser(description="NIST Compliance RAG Demo")
    parser.add_argument('--model', type=str, default='all-mpnet-base-v2', help='SentenceTransformer model name')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config.ini')
    stig_folder = config.get('DEFAULT', 'stig_folder', fallback='./stigs')
    nist_800_53_xls_url = config.get('DEFAULT', 'nist_800_53_xls_url')
    catalog_url = config.get('DEFAULT', 'catalog_url')
    high_baseline_url = config.get('DEFAULT', 'high_baseline_url')
    nist_800_53a_json_url = config.get('DEFAULT', 'nist_800_53a_json_url')
    excel_local_path = os.path.join(KNOWLEDGE_DIR, 'sp800-53r5-control-catalog.xlsx')

    # Fetch catalog data (prefer JSON over Excel if available)
    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 catalog data...{Style.RESET_ALL}")
    catalog_json = fetch_json_data(catalog_url)
    if catalog_json:
        catalog_data = extract_controls_from_json(catalog_json)
    else:
        catalog_excel = fetch_excel_data(nist_800_53_xls_url, excel_local_path)
        catalog_data = extract_controls_from_excel(catalog_excel) if catalog_excel else []

    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 High baseline JSON data...{Style.RESET_ALL}")
    high_baseline_json = fetch_json_data(high_baseline_url)
    high_baseline_data = extract_high_baseline_controls(high_baseline_json) if high_baseline_json else []

    print(f"{Fore.CYAN}Fetching NIST SP 800-53A assessment procedures JSON data...{Style.RESET_ALL}")
    assessment_json = fetch_json_data(nist_800_53a_json_url)
    assessment_procedures = extract_assessment_procedures(assessment_json) if assessment_json else {}

    all_documents = []
    for ctrl in catalog_data:
        base_doc = f"NIST 800-53 Rev 5 Catalog, {ctrl['control_id']}: {ctrl['title']} {ctrl['description']}"
        all_documents.append(base_doc)
        assess_doc = f"NIST 800-53 Rev 5 Assessment, {ctrl['control_id']}: To assess this control, verify {ctrl['description'].lower()} Check parameters: {', '.join(ctrl['parameters']) if ctrl['parameters'] else 'none specified'}."
        all_documents.append(assess_doc)
    all_documents.extend(high_baseline_data)

    print(f"{Fore.CYAN}Building new vector store (this may take a moment)...{Style.RESET_ALL}")
    model, index, doc_list = build_vector_store(all_documents, args.model)

    print(f"{Fore.CYAN}Loading CCI-to-NIST mapping...{Style.RESET_ALL}")
    cci_to_nist = load_cci_mapping('U_CCI_List.xml')
    print(f"CCI mappings loaded: {len(cci_to_nist)}")
    print("Sample CCI mappings:", list(cci_to_nist.items())[:5])

    print(f"{Fore.CYAN}Loading STIG data from folder: {stig_folder}{Style.RESET_ALL}")
    all_stig_recommendations, available_stigs = load_stig_data(stig_folder, cci_to_nist)
    print(f"Available STIGs: {len(available_stigs)}")
    print("Sample STIGs:", available_stigs[:2])

    control_details = {ctrl['control_id']: ctrl for ctrl in catalog_data}
    high_baseline_controls = {normalize_control_id(entry.split(', ')[1].split(': ')[0]) for entry in high_baseline_data}

    print(f"{Fore.GREEN}Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog, 800-53A, and STIG Knowledge{Style.RESET_ALL}")
    print("Type 'help' for examples, 'list stigs' to see available STIGs, 'exit' to quit.\n")

    while True:
        query = input(f"{Fore.YELLOW}Enter your compliance question (e.g., 'How should IA-5 be implemented for Windows?' or 'How do I assess AU-3?'): {Style.RESET_ALL}").strip()
        if query.lower() == 'exit':
            break
        if query.lower() == 'help':
            print("Examples:")
            print("- How should IA-5 be implemented for Windows?")
            print("- How do I assess AU-3?")
            print("- List STIGs")
            print("- List STIGs for Red Hat")
            print("- What is AC-7?")
            continue
        if not query:
            continue

        print(f"\n{Fore.CYAN}Processing...{Style.RESET_ALL}")
        retrieved_docs = retrieve_documents(query, model, index, doc_list, top_k=100)
        response = generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures)
        print(f"\n{Fore.CYAN}### Response to '{query}'{Style.RESET_ALL}\n{response}\n")

if __name__ == "__main__":
    main()
