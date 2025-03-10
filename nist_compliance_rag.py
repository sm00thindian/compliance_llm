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
import pdfplumber
import pickle
from tqdm import tqdm
import xml.etree.ElementTree as ET
import glob

# Configure logging to debug.log file
logging.basicConfig(
    filename='debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)
logging.getLogger('pdfminer').setLevel(logging.INFO)

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

def fetch_pdf_data(url):
    """Fetch PDF data from a URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Fetched data from {url}")
        return io.BytesIO(response.content)
    except requests.RequestException as e:
        logging.error(f"Failed to fetch PDF data from {url}: {e}")
        return None

def extract_prose(parts):
    """Recursively extract prose from control parts without extra spaces."""
    prose_list = []
    for part in parts:
        if "prose" in part:
            prose_list.append(part["prose"].strip())
        if "parts" in part:
            prose_list.extend(extract_prose(part["parts"]))
    return " ".join(prose_list).replace("  ", " ")  # Remove extra spaces

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
            description = extract_prose(control.get('parts', []))
            related_controls = [link.get('href', '').replace('#', '') for link in control.get('links', []) if link.get('rel') == 'related']
            controls.append({
                'control_id': control_id,
                'title': title,
                'description': description,
                'parameters': param_texts,
                'related_controls': related_controls
            })
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 catalog.")
    return controls

def extract_assessment_from_pdf(pdf_file):
    """Extract assessment procedures from NIST 800-53A PDF incrementally."""
    assessment_entries = []
    with pdfplumber.open(pdf_file) as pdf:
        logging.debug(f"Processing PDF with {len(pdf.pages)} pages")
        current_control = None
        current_block = ""
        for page in tqdm(pdf.pages, desc="Extracting assessment procedures"):
            text = page.extract_text() or ""
            logging.debug(f"Page text sample: {text[:200]}")
            blocks = re.split(r'(^[A-Z]{2}-[0-9]{1,2}(?:\s*\([a-z0-9]+\))?)', text, flags=re.MULTILINE)
            logging.debug(f"Found {len(blocks)} blocks on page")
            for i, block in enumerate(blocks):
                if i % 2 == 1:
                    if current_control and current_block:
                        process_block(current_control, current_block, assessment_entries)
                    current_control = block.strip().replace(' ', '')
                    current_block = ""
                elif current_control:
                    current_block += block
                    logging.debug(f"Block for {current_control}: {current_block[:200]}")
        if current_control and current_block:
            process_block(current_control, current_block, assessment_entries)
    logging.info(f"Parsed {len(assessment_entries)} assessment entries from NIST 800-53A Rev 5 PDF")
    return assessment_entries

def process_block(control_id, block, assessment_entries):
    """Process a single control block and append to assessment_entries."""
    examine = re.findall(r'(?:Examine|EXAMINE):.*?(?=Interview:|$)', block, re.DOTALL | re.IGNORECASE)
    interview = re.findall(r'(?:Interview|INTERVIEW):.*?(?=Test:|$)', block, re.DOTALL | re.IGNORECASE)
    test = re.findall(r'(?:Test|TEST):.*?(?=Examine:|$)', block, re.DOTALL | re.IGNORECASE)
    procedures = []
    for e in examine:
        procedures.append(f"Examine: {e.strip().replace('Examine:', '', 1).replace('EXAMINE:', '', 1).strip()}")
    for i in interview:
        procedures.append(f"Interview: {i.strip().replace('Interview:', '', 1).replace('INTERVIEW:', '', 1).strip()}")
    for t in test:
        procedures.append(f"Test: {t.strip().replace('Test:', '', 1).replace('TEST:', '', 1).strip()}")
    if not procedures and block.strip():
        procedures.append(f"Procedure: {block.strip()}")
    if procedures:
        assessment_entries.append(f"NIST 800-53A Rev 5 Assessment Objectives, {control_id}: {' '.join(procedures)}")

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

def extract_supplemental_guidance_from_pdf(pdf_file):
    """Extract supplemental guidance from NIST 800-53 PDF incrementally."""
    supplemental_entries = []
    with pdfplumber.open(pdf_file) as pdf:
        logging.debug(f"Processing PDF with {len(pdf.pages)} pages")
        current_control = None
        current_block = ""
        for page in tqdm(pdf.pages, desc="Extracting supplemental guidance"):
            text = page.extract_text() or ""
            blocks = re.split(r'(^[A-Z]{2}-[0-9]{1,2}(?:\s*\([a-z]+\))?)', text, flags=re.MULTILINE)
            for i, block in enumerate(blocks):
                if i % 2 == 1:
                    if current_control and current_block:
                        process_supplemental_block(current_control, current_block, supplemental_entries)
                    current_control = block.strip().replace(' ', '')
                    current_block = ""
                elif current_control:
                    current_block += block
        if current_control and current_block:
            process_supplemental_block(current_control, current_block, supplemental_entries)
    logging.info(f"Parsed {len(supplemental_entries)} supplemental guidance entries from NIST 800-53 PDF")
    return supplemental_entries

def process_supplemental_block(control_id, block, supplemental_entries):
    """Process a single supplemental guidance block."""
    discussion = re.search(r'Discussion\s*(.*?)(?:Related Controls|$)', block, re.DOTALL)
    discussion_text = discussion.group(1).strip() if discussion else ""
    supplemental_entries.append(f"NIST 800-53 Rev 5 Supplemental Guidance, {control_id}: {block.strip()}. Discussion: {discussion_text}")

def load_cci_mapping(cci_file):
    """Load CCI to NIST control mappings from U_CCI_List.xml with flexible parsing."""
    cci_to_nist = {}
    try:
        tree = ET.parse(cci_file)
        root = tree.getroot()
        ns = {'ns': 'http://iase.disa.mil/cci'}
        cci_items = root.findall('.//ns:cci_item', ns)
        logging.debug(f"Found {len(cci_items)} cci_item elements")
        for cci_item in cci_items:
            cci_id = cci_item.get('id')
            references = cci_item.findall('.//ns:reference', ns)
            for ref in references:
                if ref.get('title') == 'NIST SP 800-53':
                    control_id_elem = ref.find('ns:item', ns)
                    control_id = control_id_elem.text if control_id_elem is not None else ref.text
                    if control_id and re.match(r'[A-Z]{2}-[0-9]+', control_id):
                        cci_to_nist[cci_id] = normalize_control_id(control_id)
                        break  # One mapping per CCI
        logging.info(f"Loaded {len(cci_to_nist)} CCI-to-NIST mappings from {cci_file}")
    except Exception as e:
        logging.error(f"Failed to load CCI mappings from {cci_file}: {e}")
        # Fallback mappings for critical controls
        cci_to_nist = {
            'CCI-000196': 'IA-5',
            'CCI-000048': 'AC-7',
            'CCI-002450': 'SC-13'
        }
        logging.info(f"Using fallback CCI-to-NIST mapping with {len(cci_to_nist)} entries.")
    return cci_to_nist

def parse_stig_xccdf(xccdf_data, cci_to_nist):
    """Parse STIG XCCDF file with namespace handling to extract rules and map them to NIST controls via CCI."""
    try:
        root = ET.fromstring(xccdf_data)
        ns = {'xccdf': 'http://checklists.nist.gov/xccdf/1.1'}
        
        # Extract title with namespace
        title_elem = root.find('.//xccdf:title', ns)
        title = title_elem.text if title_elem is not None and title_elem.text else "Untitled STIG"
        
        # Derive technology from title
        technology = title.split(' ')[0] if title != "Untitled STIG" else "Unknown"
        
        # Extract benchmark ID and version
        benchmark_id = root.get('id', 'Unknown')
        version_elem = root.find('.//xccdf:version', ns)
        version = version_elem.text if version_elem is not None else "Unknown"
        
        stig_recommendations = {}
        for rule in root.findall('.//xccdf:Rule', ns):
            rule_id = rule.get('id')
            title_elem = rule.find('.//xccdf:title', ns)
            title_text = title_elem.text if title_elem is not None and title_elem.text else "No title"
            fix_elem = rule.find('.//xccdf:fix', ns)
            fix_text = fix_elem.text if fix_elem is not None and fix_elem.text else "No fix instructions provided."
            ccis = rule.findall('.//xccdf:ident[@system="http://cyber.mil/cci"]', ns)
            for cci in ccis:
                cci_id = cci.text
                control_id = cci_to_nist.get(cci_id)
                if control_id:
                    if control_id not in stig_recommendations:
                        stig_recommendations[control_id] = []
                    stig_recommendations[control_id].append({
                        'rule_id': rule_id,
                        'title': title_text,
                        'fix': fix_text
                    })
        logging.info(f"Parsed STIG data for technology: {technology}, mapped to {len(stig_recommendations)} NIST controls.")
        return stig_recommendations, technology, title, benchmark_id, version
    except Exception as e:
        logging.error(f"Failed to parse STIG XCCDF: {e}")
        raise

def load_stig_data(stig_folder, cci_to_nist):
    """Load STIG data from XCCDF files in the specified folder."""
    all_stig_recommendations = {}
    available_stigs = []
    for stig_file in glob.glob(os.path.join(stig_folder, '*.xml')):
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
        except Exception as e:
            logging.error(f"Failed to load STIG file '{stig_file}': {e}")
    logging.info(f"Loaded STIG recommendations for {len(all_stig_recommendations)} technologies.")
    return all_stig_recommendations, available_stigs

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs):
    """Generate a response to the user’s query with improved content and readability."""
    query_lower = query.lower()
    
    if "list stigs" in query_lower:
        keyword = None
        if "for" in query_lower:
            parts = query_lower.split("for")
            if len(parts) > 1:
                keyword = parts[1].strip()
        filtered_stigs = [stig for stig in available_stigs if not keyword or keyword.lower() in stig['technology'].lower() or keyword.lower() in stig['title'].lower()]
        if not filtered_stigs:
            return f"No STIGs found for '{keyword}'." if keyword else "No STIGs loaded. Check the stig_folder in config.ini and ensure valid XCCDF files are present."
        response = ["### Available STIGs"]
        response.append(f"{'File':<30} {'Title':<50} {'Technology':<20} {'Benchmark ID':<30} {'Version':<10}")
        for stig in filtered_stigs:
            response.append(f"{stig['file']:<30} {stig['title']:<50} {stig['technology']:<20} {stig['benchmark_id']:<30} {stig['version']:<10}")
        return "\n\n".join(response)
    
    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2}(?:\s*\([a-zA-Z0-9]+\))?)\b')
    control_matches = control_pattern.findall(query.upper())
    control_ids = [normalize_control_id(match.replace(' ', '')) for match in control_matches]
    steps = []

    for control_id in control_ids:
        if control_id in control_details:
            ctrl = control_details[control_id]
            steps.append(f"#### What is {control_id}?\n**Title:** {ctrl['title']}\n\n**Description:** {ctrl['description']}\n\n**Parameters:** {'; '.join(ctrl['parameters']) if ctrl['parameters'] else 'None'}\n\n**Related Controls:** {', '.join(ctrl['related_controls']) if ctrl['related_controls'] else 'None'}")
            if control_id in high_baseline_controls:
                steps.append("**Status:** Included in High baseline.")

    if "implement" in query_lower and control_ids:
        for target in control_ids:
            steps.append(f"#### How to Implement {target}:")
            assessment_procedures = []
            guidance_texts = []
            
            for doc in retrieved_docs:
                doc_control = re.search(r'(?:NIST 800-53A Rev 5 Assessment Objectives|NIST 800-53 Rev 5 Supplemental Guidance|NIST 800-53 Rev 5 Catalog), ([A-Z]{2}-[0-9]+(?:\([a-z0-9]+\))?)', doc)
                if doc_control and normalize_control_id(doc_control.group(1)) == target:
                    if "NIST 800-53A Rev 5 Assessment Objectives" in doc:
                        lines = doc.split(': ', 1)[1].split('. ')
                        for line in lines:
                            if "Examine:" in line:
                                assessment_procedures.append(f"Examine: {line.split('Examine: ')[1]}")
                            elif "Interview:" in line:
                                assessment_procedures.append(f"Interview: {line.split('Interview: ')[1]}")
                            elif "Test:" in line:
                                assessment_procedures.append(f"Test: {line.split('Test: ')[1]}")
                            elif "Procedure:" in line:
                                assessment_procedures.append(f"Procedure: {line.split('Procedure: ')[1]}")
                    elif "NIST 800-53 Rev 5 Supplemental Guidance" in doc or "NIST 800-53 Rev 5 Catalog" in doc:
                        guidance_text = doc.split(': ', 1)[1].split(' Related Controls')[0].split(' Discussion: ')[0].strip()
                        if guidance_text:
                            guidance_texts.append(guidance_text)
                        discussion = re.search(r'Discussion: (.*?)(?: Related Controls|$)', doc)
                        if discussion:
                            guidance_texts.append(f"Discussion: {discussion.group(1)}")
            
            if assessment_procedures:
                steps.append("**Assessment Procedures:**")
                for proc in assessment_procedures:
                    steps.append(f"- {proc}")
            else:
                steps.append("**Assessment Procedures:**\n- None retrieved; ensure policies are tested per organizational needs.")
            
            if guidance_texts:
                steps.append("**Guidance:**")
                for guidance in guidance_texts:
                    steps.append(f"- {guidance}")
            else:
                steps.append("**Guidance:**\n- None retrieved; follow NIST 800-53 catalog requirements.")
            
            for technology, stig_recommendations in all_stig_recommendations.items():
                recommendations = stig_recommendations.get(target, [])
                if recommendations:
                    steps.append(f"**STIG Recommendations for {technology}:**")
                    for rec in recommendations:
                        steps.append(f"- Rule {rec['rule_id']}: {rec['title']}\n  - Fix: {rec['fix']}")
                else:
                    steps.append(f"**STIG Recommendations for {technology}:**\n- None found for this control.")

    if not steps:
        steps.append("No specific information found for your query. Try rephrasing or check the NIST 800-53 documentation at nist.gov.")

    return "\n\n".join(steps)

def build_vector_store(documents, model_name):
    """Build or load a FAISS vector store from documents."""
    index_file = f"faiss_index_{hashlib.md5(model_name.encode()).hexdigest()}.pkl"
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
    logging.info(f"Sample retrieved docs: {[doc[:100] for doc in retrieved_docs[:5]]}")
    return retrieved_docs

def main():
    parser = argparse.ArgumentParser(description="NIST Compliance RAG Demo")
    parser.add_argument('--model', type=str, default='all-mpnet-base-v2', help='SentenceTransformer model name')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config.ini')
    stig_folder = config.get('Paths', 'stig_folder', fallback='./stigs')

    print("Fetching NIST OSCAL SP 800-53 Rev 5 catalog data...")
    catalog_json = fetch_json_data('https://raw.githubusercontent.com/usnistgov/oscal-content/refs/heads/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json')
    oscal_data = extract_controls_from_json(catalog_json)

    print("Fetching NIST SP 800-53A Rev 5 assessment procedures PDF...")
    assessment_pdf = fetch_pdf_data('https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53Ar5.pdf')
    assessment_data = extract_assessment_from_pdf(assessment_pdf) if assessment_pdf else []

    print("Fetching NIST SP 800-53 Rev 5 High baseline data...")
    high_baseline_json = fetch_json_data('https://raw.githubusercontent.com/usnistgov/oscal-content/refs/heads/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_HIGH-baseline_profile.json')
    high_baseline_data = extract_high_baseline_controls(high_baseline_json) if high_baseline_json else []

    print("Fetching NIST SP 800-53 Rev 5 PDF for supplemental guidance...")
    supplemental_pdf = fetch_pdf_data('https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf')
    supplemental_data = extract_supplemental_guidance_from_pdf(supplemental_pdf) if supplemental_pdf else []

    all_documents = [f"{ctrl['control_id']}: {ctrl['title']} {ctrl['description']}" for ctrl in oscal_data] + assessment_data + high_baseline_data + supplemental_data

    print("Building new vector store (this may take a moment)...")
    model, index, doc_list = build_vector_store(all_documents, args.model)

    print("Loading CCI-to-NIST mapping...")
    cci_to_nist = load_cci_mapping('U_CCI_List.xml')

    print(f"Loading STIG data from folder: {stig_folder}")
    all_stig_recommendations, available_stigs = load_stig_data(stig_folder, cci_to_nist)

    # Create control details dictionary
    control_details = {ctrl['control_id']: ctrl for ctrl in oscal_data}

    # Create set of controls in High baseline
    high_baseline_controls = set()
    for entry in high_baseline_data:
        parts = entry.split(', ', 1)
        if len(parts) == 2:
            control_id = normalize_control_id(parts[1].split(': ')[0])
            high_baseline_controls.add(control_id)

    print("Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog, 800-53A Rev 5 Assessment, High Baseline, Supplemental Guidance, and STIG Knowledge")
    print("Type 'help' for examples, 'list stigs' to see available STIGs, 'exit' to quit.\n")

    while True:
        query = input("Enter your compliance question (e.g., 'How should AU-2 be implemented?'): ").strip()
        if query.lower() == 'exit':
            break
        if query.lower() == 'help':
            print("Examples:")
            print("- How should AU-2 be implemented?")
            print("- List STIGs")
            print("- List STIGs for Red Hat")
            print("- What is IA-5?")
            continue
        if not query:
            continue

        print("\nProcessing...")
        retrieved_docs = retrieve_documents(query, model, index, doc_list, top_k=100)
        response = generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs)
        print(f"\n### {query}\n{response}\n")

if __name__ == "__main__":
    main()
