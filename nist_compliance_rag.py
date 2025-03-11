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
            params = control.get('parameters', [])
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

def load_cci_mapping(cci_file):
    """Load CCI-to-NIST mapping from U_CCI_List.xml."""
    cci_to_nist = {}
    try:
        tree = ET.parse(cci_file)
        root = tree.getroot()
        ns = {'ns': 'http://iase.disa.mil/cci'}
        for cci_item in root.findall('.//ns:cci_item', ns):
            cci_id = cci_item.get('id')
            for ref in cci_item.findall('.//ns:reference', ns):
                if ref.get('title') == 'NIST SP 800-53':
                    control_id = ref.get('index')
                    if control_id and re.match(r'[A-Z]{2}-[0-9]+', control_id.split()[0]):
                        cci_to_nist[cci_id] = normalize_control_id(control_id.split()[0])
                        break
        logging.info(f"Loaded {len(cci_to_nist)} CCI-to-NIST mappings from {cci_file}")
    except Exception as e:
        logging.error(f"CCI mapping failed: {e}")
        cci_to_nist = {'CCI-000196': 'IA-5', 'CCI-000048': 'AC-7', 'CCI-002450': 'SC-13'}
        logging.info(f"Using fallback CCI-to-NIST mapping with {len(cci_to_nist)} entries.")
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

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs):
    """Generate a user-friendly response to a query about NIST 800-53 controls or STIGs."""
    query_lower = query.lower()
    response = []

    # Quick summary intro with color
    if "list stigs" not in query_lower:
        response.append(f"{Fore.YELLOW}**Answering:** '{query}'{Style.RESET_ALL}")
        response.append(f"Here’s what I found based on NIST 800-53 and available STIGs:\n")

    # Handle "list stigs" query
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

    # Parse control IDs and system type from query
    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2}(?:\s*\([a-zA-Z0-9]+\))?)\b')
    control_ids = [match.replace(' ', '') for match in control_pattern.findall(query.upper())]
    system_match = re.search(r'for\s+([Windows|Linux|Red Hat|Ubuntu|macOS|Cisco].*?)(?:\s|$)', query, re.IGNORECASE)
    system_type = system_match.group(1).strip().rstrip('?') if system_match else None

    if control_ids:
        response.append(f"{Fore.YELLOW}**Controls Covered:** {', '.join(control_ids)}{Style.RESET_ALL}" + (f" for {system_type}" if system_type else ""))
    else:
        response.append(f"{Fore.RED}**No NIST controls detected.**{Style.RESET_ALL} Try including a control ID like 'AU-3'.")
        return "\n\n".join(response)

    # NIST control details
    for control_id in control_ids:
        if control_id in control_details:
            ctrl = control_details[control_id]
            response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
            response.append(f"- **Title:** {ctrl['title']}")
            response.append(f"- **Description:** {ctrl['description']}")
            response.append(f"- **Parameters:** {', '.join(ctrl['parameters']) if ctrl['parameters'] else 'None specified'}")
            response.append(f"- **Related Controls:** {', '.join(ctrl['related_controls']) if ctrl['related_controls'] else 'None'}")
            if control_id in high_baseline_controls:
                response.append(f"- **Baseline:** Included in the High baseline")
            response.append(f"\n**Learn More:** [NIST 800-53 Catalog](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)")
        else:
            response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
            response.append(f"- **Status:** Not found in the catalog.")

    # STIG implementation guidance
    if "implement" in query_lower and control_ids:
        for control_id in control_ids:
            response.append(f"{Fore.CYAN}### Implementation Guidance for {Fore.YELLOW}{control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            guidance = [doc.split(': ', 1)[1] for doc in retrieved_docs if control_id in doc]
            response.append(f"{Fore.CYAN}#### NIST Guidance{Style.RESET_ALL}")
            if guidance:
                response.extend(f"- {g}" for g in guidance)
            else:
                response.append("- No specific NIST guidance found. Check the control’s description.")

            stig_found = False
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type:
                    system_lower = system_type.lower()
                    if system_lower not in tech_lower and 'windows' not in tech_lower and 'microsoft' not in tech_lower:
                        continue
                if control_id in recs:
                    response.append(f"{Fore.CYAN}#### STIG Recommendations for {tech}{Style.RESET_ALL}")
                    for rec in recs[control_id]:
                        short_title = rec['title'].split(' - ')[0][:50] + "..." if len(rec['title']) > 50 else rec['title']
                        response.append(f"- **{Fore.YELLOW}{short_title}{Style.RESET_ALL}** (Rule {rec['rule_id']})")
                        
                        fix_lines = rec['fix'].split('. ')
                        if len(fix_lines) > 1 and len(rec['fix']) > 100:
                            response.append(f"  - {Fore.GREEN}**Steps to Fix:**{Style.RESET_ALL}")
                            response.extend(f"    - {line.strip()}." for line in fix_lines if line.strip())
                        else:
                            response.append(f"  - {Fore.GREEN}**Fix:**{Style.RESET_ALL} {rec['fix']}")
                        
                        family = control_id.split('-')[0]
                        why = {
                            'AU': 'Ensures actions are tracked for accountability.',
                            'IA': 'Protects against unauthorized access.',
                            'SC': 'Secures system communications.'
                        }.get(family, 'Improves system security.')
                        response.append(f"  - {Fore.MAGENTA}**Why:**{Style.RESET_ALL} {why}")
                    response.append(f"\n**More Info:** [DISA STIGs](https://public.cyber.mil/stigs/downloads/)")
                    stig_found = True
            if not stig_found:
                response.append(f"{Fore.CYAN}#### STIG Recommendations{Style.RESET_ALL}")
                response.append(f"- No STIGs found for this control{' on ' + system_type if system_type else ''}. Try the DISA STIG website.")

    if len(response) <= 2:  # Only summary lines
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
    excel_local_path = os.path.join(KNOWLEDGE_DIR, 'sp800-53r5-control-catalog.xlsx')

    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 catalog Excel data...{Style.RESET_ALL}")
    catalog_excel = fetch_excel_data(nist_800_53_xls_url, excel_local_path)
    catalog_data = extract_controls_from_excel(catalog_excel) if catalog_excel else []

    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 High baseline JSON data...{Style.RESET_ALL}")
    high_baseline_json = fetch_json_data(config.get('DEFAULT', 'high_baseline_url'))
    high_baseline_data = extract_high_baseline_controls(high_baseline_json) if high_baseline_json else []

    all_documents = [f"NIST 800-53 Rev 5 Catalog, {ctrl['control_id']}: {ctrl['title']} {ctrl['description']}" for ctrl in catalog_data] + high_baseline_data

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

    print(f"{Fore.GREEN}Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog and STIG Knowledge{Style.RESET_ALL}")
    print("Type 'help' for examples, 'list stigs' to see available STIGs, 'exit' to quit.\n")

    while True:
        query = input(f"{Fore.YELLOW}Enter your compliance question (e.g., 'How should AU-3 be implemented for Windows?'): {Style.RESET_ALL}").strip()
        if query.lower() == 'exit':
            break
        if query.lower() == 'help':
            print("Examples:")
            print("- How should AU-3 be implemented for Windows?")
            print("- List STIGs")
            print("- List STIGs for Red Hat")
            print("- What is IA-5?")
            continue
        if not query:
            continue

        print(f"\n{Fore.CYAN}Processing...{Style.RESET_ALL}")
        retrieved_docs = retrieve_documents(query, model, index, doc_list, top_k=100)
        response = generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs)
        print(f"\n{Fore.CYAN}### Response to '{query}'{Style.RESET_ALL}\n{response}\n")

if __name__ == "__main__":
    main()
