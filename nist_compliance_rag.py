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

# Setup logging
logging.basicConfig(filename='debug.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Utility function to normalize control IDs
def normalize_control_id(control_id):
    return control_id.replace('-0', '-').upper()

# Fetch data from URL with caching
def fetch_data(url, cache_file):
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return f.read()
    response = requests.get(url)
    response.raise_for_status()
    data = response.content
    with open(cache_file, 'wb') as f:
        f.write(data)
    logging.info(f"Fetching data from {url}")
    return data

# Parse OSCAL JSON data (for catalog)
def parse_oscal_json(json_data):
    try:
        data = json.loads(json_data.decode('utf-8'))
        logging.info(f"Raw JSON keys: {list(data.keys())}")
        
        controls = None
        if 'catalog' in data:
            catalog = data['catalog']
            logging.info(f"Catalog subkeys: {list(catalog.keys())}")
            if 'controls' in catalog:
                controls = catalog['controls']
            elif 'groups' in catalog:
                controls = []
                for group in catalog['groups']:
                    if 'controls' in group:
                        controls.extend(group['controls'])
        
        if not controls:
            raise ValueError("No recognizable control structure found in JSON")
        
        compliance_data = []

        def extract_controls(control_list):
            for control in control_list:
                control_id = normalize_control_id(control['id'])
                title = control.get('title', 'No title')
                parts = control.get('parts', [])
                narrative_parts = []
                for part in parts:
                    if part.get('name') == 'statement':
                        text = part.get('prose', '')
                        subparts = part.get('parts', [])
                        narrative_parts.append(text)
                        for subpart in subparts:
                            if subpart.get('name').startswith(control_id.lower()):
                                narrative_parts.append(f"{subpart.get('name').split('.')[-1]}. {subpart.get('prose', '')}")
                narrative = ' '.join(narrative_parts).strip()
                props = control.get('props', [])
                discussion = next((prop['value'] for prop in props if prop.get('name') == 'discussion'), '')
                full_text = f"NIST 800-53 Rev 5 Catalog, {control_id}: {title}. {narrative} Discussion: {discussion}".strip()
                compliance_data.append(full_text)
                if 'controls' in control:
                    extract_controls(control['controls'])

        extract_controls(controls)
        logging.info(f"Loaded {len(compliance_data)} controls from NIST 800-53 Rev 5 catalog.")
        return compliance_data
    except Exception as e:
        logging.error(f"Failed to parse OSCAL JSON: {e}")
        raise

# Parse assessment procedures text with improved control ID association
def parse_assessment_text(text_data):
    text = text_data.decode('utf-8')
    lines = text.splitlines()
    compliance_data = []
    current_entry = []
    current_control = None
    header_pattern = re.compile(r'^([A-Z]{2}-[0-9]{1,2})\s+[A-Z ,]+')  # Matches "AU-02 EVENT LOGGING"

    for line in lines:
        header_match = header_pattern.match(line.strip())
        if header_match:
            if current_entry and current_control:
                compliance_data.append(f"NIST 800-53A Rev 5 Assessment Objectives, {current_control}: {' '.join(current_entry).strip()}")
            current_control = normalize_control_id(header_match.group(1))  # e.g., "AU-2"
            current_entry = []
        elif line.strip().startswith(('Examine:', 'Interview:', 'Test:')) or 'ASSESSMENT OBJECTIVE' in line:
            if current_entry and current_control:
                compliance_data.append(f"NIST 800-53A Rev 5 Assessment Objectives, {current_control}: {' '.join(current_entry).strip()}")
            current_entry = [line]
        elif line.strip():
            current_entry.append(line)

    if current_entry and current_control:
        compliance_data.append(f"NIST 800-53A Rev 5 Assessment Objectives, {current_control}: {' '.join(current_entry).strip()}")

    logging.info(f"Loaded {len(compliance_data)} entries from NIST 800-53A Rev 5 assessment procedures.")
    return compliance_data

# Parse high baseline JSON
def parse_high_baseline_json(json_data):
    try:
        data = json.loads(json_data.decode('utf-8'))
        controls = []
        if 'catalog' in data and 'groups' in data['catalog']:
            for group in data['catalog']['groups']:
                if 'controls' in group:
                    controls.extend(group['controls'])
        compliance_data = [f"NIST 800-53 Rev 5 High Baseline, {normalize_control_id(ctrl['id'])}" for ctrl in controls]
        logging.info(f"Loaded {len(compliance_data)} controls from NIST 800-53 Rev 5 High baseline.")
        return compliance_data
    except Exception as e:
        logging.error(f"Failed to parse high baseline JSON: {e}")
        raise

# Parse NIST 800-53 PDF for supplemental guidance
def parse_nist_800_53_pdf(pdf_data):
    compliance_data = []
    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2})\b')
    related_controls_pattern = re.compile(r'Related Controls?:?\s*([A-Z]{2}-[0-9]{1,2}(?:,\s*[A-Z]{2}-[0-9]{1,2})*)', re.IGNORECASE)
    
    with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
        full_text = ""
        started = False
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text += text + "\n\n"
            if not started and ("AC-1" in text.upper()):
                started = True
        
        lines = full_text.splitlines()
        current_control = None
        guidance_lines = []
        related_controls = []
        in_guidance = False
        
        for line in lines:
            line = line.strip()
            control_match = control_pattern.search(line)
            if control_match and started:
                new_control = normalize_control_id(control_match.group(1))
                if current_control and new_control != current_control:
                    guidance_text = " ".join(guidance_lines).strip()
                    related_text = f"Related Controls: {', '.join(related_controls)}" if related_controls else ""
                    if guidance_text or related_text:
                        compliance_data.append(f"NIST 800-53 Rev 5 Supplemental Guidance, {current_control}: {guidance_text} {related_text}")
                    guidance_lines = []
                    related_controls = []
                    in_guidance = True
                current_control = new_control
            elif current_control and started and in_guidance:
                related_match = related_controls_pattern.search(line)
                if related_match:
                    related_controls = [normalize_control_id(ctrl.strip()) for ctrl in related_match.group(1).split(',')]
                elif "Control Enhancements" in line or "References" in line or "Priority and Baseline Allocation" in line:
                    in_guidance = False
                else:
                    guidance_lines.append(line)
        
        if current_control:
            guidance_text = " ".join(guidance_lines).strip()
            related_text = f"Related Controls: {', '.join(related_controls)}" if related_controls else ""
            if guidance_text or related_text:
                compliance_data.append(f"NIST 800-53 Rev 5 Supplemental Guidance, {current_control}: {guidance_text} {related_text}")
    
    logging.info(f"Parsed {len(compliance_data)} supplemental guidance entries from NIST 800-53 PDF")
    return compliance_data

# Build or load vector store
def build_vector_store(documents, embedder, vector_file, docs_file, hash_file):
    data_hash = hashlib.sha256(''.join(documents).encode()).hexdigest()
    if os.path.exists(vector_file) and os.path.exists(docs_file) and os.path.exists(hash_file):
        with open(hash_file, 'r') as f:
            stored_hash = f.read().strip()
        if stored_hash == data_hash:
            index = faiss.read_index(vector_file)
            with open(docs_file, 'rb') as f:
                loaded_docs = pickle.load(f)
            return index, loaded_docs
    
    embeddings = embedder.encode(documents, show_progress_bar=True)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
    faiss.write_index(index, vector_file)
    with open(docs_file, 'wb') as f:
        pickle.dump(documents, f)
    with open(hash_file, 'w') as f:
        f.write(data_hash)
    return index, documents

# Generate response from retrieved documents
def generate_response(query, retrieved_docs, oscal_data):
    query_lower = query.lower()
    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2})\b')
    control_matches = control_pattern.findall(query.upper())
    control_ids = [normalize_control_id(ctrl) for ctrl in control_matches]
    steps = set()

    control_details = {}
    for entry in oscal_data:
        parts = entry.split(', ', 1)
        if len(parts) < 2:
            continue
        control_id = normalize_control_id(parts[1].split(': ')[0])
        control_details[control_id] = entry.split(': ', 1)[1]

    if control_ids:
        for ctrl in control_ids:
            if ctrl in control_details:
                steps.add(f"#### What is {ctrl}?\n{control_details[ctrl]}")

    if "implement" in query_lower and control_ids:
        steps.add(f"#### How to Implement {control_ids[0]}:")
        found_assessment = False
        found_guidance = False
        for doc in retrieved_docs:
            if f"NIST 800-53A Rev 5 Assessment Objectives, {control_ids[0]}:" in doc:
                lines = doc.split(': ', 1)[1].split('. ')
                for line in lines:
                    if "Examine:" in line:
                        steps.add(f"- Examine: {line.split('Examine: ')[1]}")
                        found_assessment = True
                    elif "Interview:" in line:
                        steps.add(f"- Interview: {line.split('Interview: ')[1]}")
                        found_assessment = True
                    elif "Test:" in line:
                        steps.add(f"- Test: {line.split('Test: ')[1]}")
                        found_assessment = True
            elif f"NIST 800-53 Rev 5 Supplemental Guidance, {control_ids[0]}:" in doc or f"NIST 800-53 Rev 5 Catalog, {control_ids[0]}:" in doc:
                guidance_text = doc.split(': ', 1)[1].split(' Related Controls')[0].split(' Discussion: ')[0].strip()
                if guidance_text:
                    steps.add(f"- Guidance: {guidance_text}")
                    found_guidance = True
                discussion = re.search(r'Discussion: (.*?)(?: Related Controls|$)', doc)
                if discussion:
                    steps.add(f"- Guidance: Discussion: {discussion.group(1)}")
                    found_guidance = True
        if not found_assessment:
            steps.add("- No specific assessment procedures retrieved; ensure policies are tested per organizational needs.")
        if not found_guidance:
            steps.add("- No additional guidance retrieved; follow catalog requirements.")

    elif "evidence" in query_lower and control_ids:
        steps.add(f"#### Evidence Needed for {control_ids[0]}:")
        found_evidence = False
        for doc in retrieved_docs:
            if f"NIST 800-53A Rev 5 Assessment Objectives, {control_ids[0]}:" in doc:
                lines = doc.split(': ', 1)[1].split('. ')
                for line in lines:
                    if "Examine:" in line:
                        steps.add(f"- Examine: {line.split('Examine: ')[1]}")
                        found_evidence = True
                    elif "Interview:" in line:
                        steps.add(f"- Interview: {line.split('Interview: ')[1]}")
                        found_evidence = True
                    elif "Test:" in line:
                        steps.add(f"- Test: {line.split('Test: ')[1]}")
                        found_evidence = True
        if not found_evidence:
            steps.add("- No specific evidence requirements retrieved.")

    elif "risks" in query_lower and control_ids:
        steps.add(f"#### Risks Mitigated by {control_ids[0]}:")
        found_risks = False
        for doc in retrieved_docs:
            if control_ids[0] in doc:
                discussion = re.search(r'Discussion: (.*?)(?: Related Controls|$)', doc)
                if discussion:
                    steps.add(f"- Discussion: {discussion.group(1)}")
                    found_risks = True
        if not found_risks:
            steps.add("- No specific risk mitigation details retrieved.")

    elif "relate" in query_lower and len(control_ids) >= 2:
        steps.add(f"#### Relationship Between {control_ids[0]} and {control_ids[1]}:")
        found_relation = False
        for doc in retrieved_docs:
            if control_ids[0] in doc and "Related Controls" in doc:
                related = re.search(r'Related Controls: (.*)', doc)
                if related and control_ids[1] in related.group(1):
                    steps.add(f"- {control_ids[0]} lists {control_ids[1]} as a related control.")
                    found_relation = True
            elif control_ids[1] in doc and "Related Controls" in doc:
                related = re.search(r'Related Controls: (.*)', doc)
                if related and control_ids[0] in related.group(1):
                    steps.add(f"- {control_ids[1]} lists {control_ids[0]} as a related control.")
                    found_relation = True
        if not found_relation:
            steps.add("- No direct relationship found in retrieved data.")

    if not steps:
        steps.add("No specific information found for your query.")

    return "\n\n".join(sorted(steps))

# Main demo function with increased k
def run_demo(oscal_data, vector_store, embeddings, documents, embedder):
    print("Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog, 800-53A Rev 5 Assessment, High Baseline, and Supplemental Guidance Knowledge (Version 2.27)")
    print("Type 'help' for examples, 'exit' to quit.\n")

    while True:
        query = input("Enter your compliance question (e.g., 'How should AU-2 be implemented?'): ").strip()
        if query.lower() == 'exit':
            break
        elif query.lower() == 'help':
            print("""
            Examples:
            - "What evidence is needed for CA-7?"
            - "What risks does AC-1 mitigate?"
            - "How does SI-4 relate to SI-7?"
            - "What is AU-2?"
            - "How should AU-2 be implemented?"
            Tip: Use control IDs (e.g., AC-1) or keywords like 'evidence', 'risks', 'relate', 'implement'.
            """)
            continue
        
        print("\nProcessing...")
        logging.info(f"Processing query: {query}")
        query_embedding = embedder.encode([query])
        distances, indices = vector_store.search(query_embedding, k=50)  # Increased to 50
        
        retrieved_docs = [documents[idx] for idx in indices[0]]
        control_ids = [normalize_control_id(ctrl) for ctrl in re.findall(r'\b([A-Z]{2}-[0-9]{1,2})\b', query.upper())]
        logging.info(f"Retrieved {len(retrieved_docs)} documents for {', '.join(control_ids) if control_ids else 'query'}")
        logging.info(f"Retrieved documents: {[doc[:100] + '...' for doc in retrieved_docs]}")
        
        if control_ids:
            assessment_docs = [doc for doc in retrieved_docs if f"NIST 800-53A Rev 5 Assessment Objectives, {control_ids[0]}:" in doc]
            logging.info(f"Found {len(assessment_docs)} assessment documents for {control_ids[0]}")
        
        response = generate_response(query, retrieved_docs, oscal_data)
        print(f"### {query}\n{response}\n")

# Main execution
def main(model_name):
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    catalog_url = config['DEFAULT']['catalog_url']
    assessment_url = config['DEFAULT']['assessment_url']
    high_baseline_url = config['DEFAULT']['high_baseline_url']
    pdf_url = config['DEFAULT']['nist_800_53_pdf_url']
    vector_file = config['DEFAULT']['vector_file']
    docs_file = config['DEFAULT']['docs_file']
    hash_file = config['DEFAULT']['hash_file']
    
    embedder = SentenceTransformer(model_name)
    logging.info(f"Load pretrained SentenceTransformer: {model_name}")

    print("Fetching NIST OSCAL SP 800-53 Rev 5 catalog data...")
    catalog_data = fetch_data(catalog_url, 'catalog_cache.json')
    oscal_compliance = parse_oscal_json(catalog_data)

    print("Fetching NIST SP 800-53A Rev 5 assessment procedures text...")
    assessment_data = fetch_data(assessment_url, 'assessment_cache.txt')
    assessment_compliance = parse_assessment_text(assessment_data)

    print("Fetching NIST SP 800-53 Rev 5 High baseline data...")
    high_baseline_data = fetch_data(high_baseline_url, 'high_baseline_cache.json')
    high_baseline_compliance = parse_high_baseline_json(high_baseline_data)

    print("Fetching NIST SP 800-53 Rev 5 PDF for supplemental guidance...")
    pdf_data = fetch_data(pdf_url, 'nist_800_53_r5.pdf')
    supplemental_guidance = parse_nist_800_53_pdf(pdf_data)

    all_documents = oscal_compliance + assessment_compliance + high_baseline_compliance + supplemental_guidance

    print("Building new vector store (this may take a moment)...")
    vector_store, documents = build_vector_store(all_documents, embedder, vector_file, docs_file, hash_file)

    run_demo(oscal_compliance, vector_store, None, documents, embedder)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NIST Compliance RAG Demo")
    parser.add_argument("--model", type=str, default="all-mpnet-base-v2", help="SentenceTransformer model name")
    args = parser.parse_args()
    main(args.model)
