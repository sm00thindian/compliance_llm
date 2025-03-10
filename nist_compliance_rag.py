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

# Setup logging to overwrite each run, only for our script
logging.basicConfig(
    filename='debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'  # Overwrite instead of append
)

# Suppress pdfminer's verbose DEBUG logging
logging.getLogger('pdfminer').setLevel(logging.INFO)

def normalize_control_id(control_id):
    """Normalize control IDs by removing leading zeros and ensuring proper format."""
    parts = control_id.split('-')
    if len(parts) == 2:
        family, number = parts
        number = str(int(number))  # Remove leading zeros
        return f"{family}-{number}"
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

def extract_controls_from_json(json_data):
    """Extract controls from NIST 800-53 OSCAL JSON."""
    controls = []
    if not json_data or 'catalog' not in json_data:
        return controls
    for group in json_data['catalog'].get('groups', []):
        for control in group.get('controls', []):
            control_id = control.get('id', '').upper()
            title = control.get('title', '')
            params = control.get('parameters', [])
            param_texts = [f"{param.get('id', '')}: {param.get('label', '')}" for param in params]
            controls.append(f"NIST 800-53 Rev 5 Catalog, {control_id}: {title}. Parameters: {'; '.join(param_texts)}")
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
            blocks = re.split(r'(^[A-Z]{2}-[0-9]{1,2}\s+\([a-z0-9]+\))', text, flags=re.MULTILINE)
            for i, block in enumerate(blocks):
                if i % 2 == 1:
                    if current_control and current_block:
                        process_block(current_control, current_block, assessment_entries)
                    current_control = block.strip().replace(' ', '')
                    current_block = ""
                elif current_control:
                    current_block += block
        # Process the last block
        if current_control and current_block:
            process_block(current_control, current_block, assessment_entries)
    logging.info(f"Parsed {len(assessment_entries)} assessment entries from NIST 800-53A Rev 5 PDF")
    return assessment_entries

def process_block(control_id, block, assessment_entries):
    """Process a single control block and append to assessment_entries."""
    examine = re.findall(r'Examine:.*?(?=Interview:|$)', block, re.DOTALL)
    interview = re.findall(r'Interview:.*?(?=Test:|$)', block, re.DOTALL)
    test = re.findall(r'Test:.*?(?=Examine:|$)', block, re.DOTALL)
    procedures = []
    for e in examine:
        procedures.append(f"Examine: {e.strip().replace('Examine:', '').strip()}")
    for i in interview:
        procedures.append(f"Interview: {i.strip().replace('Interview:', '').strip()}")
    for t in test:
        procedures.append(f"Test: {t.strip().replace('Test:', '').strip()}")
    if procedures:
        assessment_entries.append(f"NIST 800-53A Rev 5 Assessment Objectives, {control_id}: {' '.join(procedures)}")

def extract_high_baseline_controls(json_data):
    """Extract controls from NIST 800-53 High baseline JSON."""
    controls = []
    if not json_data or 'profile' not in json_data:
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
            blocks = re.split(r'(^[A-Z]{2}-[0-9]{1,2}(?:\s*\([a-z]+\))?)\s+', text, flags=re.MULTILINE)
            for i, block in enumerate(blocks):
                if i % 2 == 1:
                    if current_control and current_block:
                        process_supplemental_block(current_control, current_block, supplemental_entries)
                    current_control = block.strip().replace(' ', '')
                    current_block = ""
                elif current_control:
                    current_block += block
        # Process the last block
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
    """Load CCI to NIST control mappings from U_CCI_List.xml."""
    cci_to_nist = {}
    try:
        tree = ET.parse(cci_file)
        root = tree.getroot()
        logging.debug(f"CCI XML root: {root.tag}, Attributes: {root.attrib}")
        cci_items = root.findall('.//cci_item')
        logging.debug(f"Found {len(cci_items)} cci_item elements")
        for cci_item in cci_items:
            cci_id = cci_item.get('id')
            references = cci_item.findall('.//reference')
            for reference in references:
                control_id = reference.get('title')
                if control_id and control_id.startswith(('AC-', 'AU-', 'IA-', 'SC-')):
                    cci_to_nist[cci_id] = normalize_control_id(control_id)
        logging.info(f"Loaded {len(cci_to_nist)} CCI-to-NIST mappings from {cci_file}")
    except Exception as e:
        logging.error(f"Failed to load CCI mappings from {cci_file}: {e}")
        cci_to_nist = {
            'CCI-000196': 'IA-5',
            'CCI-000048': 'AC-7',
            'CCI-002450': 'SC-13'
        }
        logging.info(f"Using fallback CCI-to-NIST mapping with {len(cci_to_nist)} entries.")
    return cci_to_nist

def parse_stig_xccdf(xccdf_data, cci_to_nist):
    """Parse STIG XCCDF file to extract rules and map them to NIST controls via CCI."""
    try:
        preview = xccdf_data[:200].decode('utf-8', errors='replace')
        logging.debug(f"STIG XCCDF data preview: {preview}")
        
        root = ET.fromstring(xccdf_data)
        if root is None:
            raise ValueError("XML parsing returned None; data may be invalid or empty.")
        
        logging.debug(f"Root element: {root.tag}, Attributes: {root.attrib}")
        
        ns = {'xccdf': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {'xccdf': 'http://checklists.nist.gov/xccdf/1.1'}
        logging.debug(f"Using namespace: {ns['xccdf']}")
        
        benchmark = root.find('xccdf:Benchmark', ns)
        if benchmark is None:
            benchmark = root.find('.//Benchmark')
            if benchmark is None:
                logging.debug(f"Children of root: {[child.tag for child in root]}")
                raise ValueError("No <Benchmark> element found in XCCDF.")
        
        title_elem = benchmark.find('xccdf:title', ns) or benchmark.find('.//title')
        if title_elem is None or not title_elem.text:
            raise ValueError("No <title> found in Benchmark or title is empty.")
        
        title = title_elem.text
        technology = title.split(' ')[0]
        stig_recommendations = {}
        
        for rule in benchmark.findall('.//xccdf:Rule', ns):
            rule_id = rule.get('id')
            title_elem = rule.find('xccdf:title', ns) or rule.find('.//title')
            title_text = title_elem.text if title_elem is not None else "No title"
            fix = rule.find('xccdf:fix', ns) or rule.find('.//fix')
            fix_text = fix.text if fix is not None else "No fix instructions provided."
            ccis = rule.findall('xccdf:ident[@system="http://cyber.mil/cci"]', ns) or rule.findall('.//ident[@system="http://cyber.mil/cci"]')
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
        return stig_recommendations, technology, title
    except ET.ParseError as e:
        logging.error(f"XML ParseError in STIG XCCDF: {e}")
        raise
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
            recommendations, technology, title = parse_stig_xccdf(xccdf_data, cci_to_nist)
            all_stig_recommendations[technology] = recommendations
            available_stigs.append({'file': os.path.basename(stig_file), 'title': title, 'technology': technology})
        except Exception as e:
            logging.error(f"Failed to load STIG file '{stig_file}': {e}")
    logging.info(f"Loaded STIG recommendations for {len(all_stig_recommendations)} technologies.")
    return all_stig_recommendations, available_stigs

def generate_response(query, retrieved_docs, oscal_data, all_stig_recommendations, available_stigs):
    """Generate a response to the user's query, including STIG recommendations or STIG list if requested."""
    query_lower = query.lower()
    
    if "list stigs" in query_lower or "what stigs are available" in query_lower:
        if not available_stigs:
            return "No STIGs loaded. Check the stig_folder in config.ini and ensure valid XCCDF files are present."
        response = ["### Available STIGs"]
        for stig in available_stigs:
            response.append(f"- File: {stig['file']}\n  Title: {stig['title']}\n  Technology: {stig['technology']}")
        return "\n\n".join(response)
    
    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2}(?:\s*\([a-zA-Z0-9]+\))?)\b')
    control_matches = control_pattern.findall(query.upper())
    control_ids = [normalize_control_id(match.replace(' ', '')) for match in control_matches]
    steps = []

    control_details = {}
    for entry in oscal_data:
        parts = entry.split(', ', 1)
        if len(parts) < 2:
            continue
        control_id = normalize_control_id(parts[1].split(': ')[0])
        control_details[control_id] = entry.split(': ', 1)[1]

    for control_id in control_ids:
        main_control = control_id.split('(')[0]
        if main_control in control_details:
            steps.append(f"#### What is {main_control}?\n{control_details[main_control]}")

    if "implement" in query_lower and control_ids:
        for target in control_ids:
            main_control = target.split('(')[0]
            steps.append(f"#### How to Implement {target}:")
            found_assessment = False
            found_guidance = False
            
            for doc in retrieved_docs:
                if f"NIST 800-53A Rev 5 Assessment Objectives, {target}:" in doc:
                    lines = doc.split(': ', 1)[1].split('. ')
                    for line in lines:
                        if "Examine:" in line:
                            steps.append(f"- Examine: {line.split('Examine: ')[1]}")
                            found_assessment = True
                        elif "Interview:" in line:
                            steps.append(f"- Interview: {line.split('Interview: ')[1]}")
                            found_assessment = True
                        elif "Test:" in line:
                            steps.append(f"- Test: {line.split('Test: ')[1]}")
                            found_assessment = True
                elif f"NIST 800-53 Rev 5 Supplemental Guidance, {target}:" in doc or f"NIST 800-53 Rev 5 Catalog, {target}:" in doc:
                    guidance_text = doc.split(': ', 1)[1].split(' Related Controls')[0].split(' Discussion: ')[0].strip()
                    if guidance_text:
                        steps.append(f"- Guidance: {guidance_text}")
                        found_guidance = True
                    discussion = re.search(r'Discussion: (.*?)(?: Related Controls|$)', doc)
                    if discussion:
                        steps.append(f"- Guidance: Discussion: {discussion.group(1)}")
                        found_guidance = True
            
            if not found_assessment:
                steps.append("- No specific assessment procedures retrieved; ensure policies are tested per organizational needs.")
            if not found_guidance:
                steps.append("- No additional guidance retrieved; follow catalog requirements.")

            for technology, stig_recommendations in all_stig_recommendations.items():
                recommendations = stig_recommendations.get(target, stig_recommendations.get(main_control, []))
                if recommendations:
                    steps.append(f"- STIG Recommendations for Implementation ({technology}):")
                    for rec in recommendations:
                        steps.append(f"  - Rule {rec['rule_id']}: {rec['title']}\n    Fix: {rec['fix']}")
                else:
                    steps.append(f"- No STIG recommendations found for this control in {technology}.")

    if not steps:
        steps.append("No specific information found for your query.")

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
    logging.info(f"Loaded pretrained SentenceTransformer: {model_name}")
    return model, index, doc_list

def retrieve_documents(query, model, index, doc_list, top_k=50):
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

    all_documents = oscal_data + assessment_data + high_baseline_data + supplemental_data

    print("Building new vector store (this may take a moment)...")
    model, index, doc_list = build_vector_store(all_documents, args.model)

    print("Loading CCI-to-NIST mapping...")
    cci_to_nist = load_cci_mapping('U_CCI_List.xml')

    print(f"Loading STIG data from folder: {stig_folder}")
    all_stig_recommendations, available_stigs = load_stig_data(stig_folder, cci_to_nist)

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
            print("- What is IA-5?")
            continue
        if not query:
            continue

        print("\nProcessing...")
        retrieved_docs = retrieve_documents(query, model, index, doc_list)
        response = generate_response(query, retrieved_docs, oscal_data, all_stig_recommendations, available_stigs)
        print(f"\n### {query}\n{response}\n")

if __name__ == "__main__":
    main()
