import argparse
import configparser
from modules.utils import setup_logging
from modules.data_fetcher import fetch_json_data, fetch_pdf_data
from modules.data_parser import extract_controls_from_json, extract_assessment_from_pdf, extract_high_baseline_controls, extract_supplemental_guidance_from_pdf, load_cci_mapping, load_stig_data
from modules.vector_store import build_vector_store
from modules.response_generator import generate_response, retrieve_documents

def main():
    setup_logging()
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

    control_details = {ctrl['control_id']: ctrl for ctrl in oscal_data}
    high_baseline_controls = {ctrl.split(', ')[1].split(': ')[0] for ctrl in high_baseline_data}

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
