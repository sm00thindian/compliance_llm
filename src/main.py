import argparse
import configparser
import logging
import os
import pickle
from colorama import init, Fore, Style
from .data_fetchers import fetch_json_data, fetch_excel_data
from .parsers import (
    extract_controls_from_json, extract_controls_from_excel,
    extract_high_baseline_controls, extract_assessment_procedures,
    load_cci_mapping, load_stig_data, normalize_control_id
)
from .vector_store import build_vector_store, retrieve_documents
from .response_generator import generate_response

init()
KNOWLEDGE_DIR = 'knowledge'
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(KNOWLEDGE_DIR, 'debug.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)

UNKNOWN_QUERIES_FILE = os.path.join(KNOWLEDGE_DIR, 'unknown_queries.pkl')

def save_unknown_query(query):
    """Save an unknown query for future training."""
    unknown_queries = load_unknown_queries()
    if query not in unknown_queries:
        unknown_queries.append(query)
        with open(UNKNOWN_QUERIES_FILE, 'wb') as f:
            pickle.dump(unknown_queries, f)
        logging.info(f"Saved unknown query: {query}")

def load_unknown_queries():
    """Load previously saved unknown queries."""
    if os.path.exists(UNKNOWN_QUERIES_FILE):
        with open(UNKNOWN_QUERIES_FILE, 'rb') as f:
            return pickle.load(f)
    return []

def main():
    parser = argparse.ArgumentParser(description="NIST Compliance RAG Demo")
    parser.add_argument('--model', type=str, default='all-mpnet-base-v2', help='SentenceTransformer model name')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config/config.ini')
    stig_folder = config.get('DEFAULT', 'stig_folder', fallback='./stigs')
    logging.debug(f"Resolved stig_folder: {os.path.abspath(stig_folder)}")
    nist_800_53_xls_url = config.get('DEFAULT', 'nist_800_53_xls_url')
    catalog_url = config.get('DEFAULT', 'catalog_url')
    high_baseline_url = config.get('DEFAULT', 'high_baseline_url')
    nist_800_53a_json_url = config.get('DEFAULT', 'nist_800_53a_json_url')
    excel_local_path = os.path.join(KNOWLEDGE_DIR, 'sp800-53r5-control-catalog.xlsx')

    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 catalog data...{Style.RESET_ALL}")
    catalog_json = fetch_json_data(catalog_url)
    catalog_data = extract_controls_from_json(catalog_json) if catalog_json else extract_controls_from_excel(fetch_excel_data(nist_800_53_xls_url, excel_local_path))

    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 High baseline JSON data...{Style.RESET_ALL}")
    high_baseline_json = fetch_json_data(high_baseline_url)
    high_baseline_data = extract_high_baseline_controls(high_baseline_json) if high_baseline_json else []

    print(f"{Fore.CYAN}Fetching NIST SP 800-53A assessment procedures JSON data...{Style.RESET_ALL}")
    assessment_json = fetch_json_data(nist_800_53a_json_url)
    assessment_procedures = extract_assessment_procedures(assessment_json) if assessment_json else {}

    all_documents = [
        f"NIST 800-53 Rev 5 Catalog, {ctrl['control_id']}: {ctrl['title']} {ctrl['description']}"
        for ctrl in catalog_data
    ] + [
        f"NIST 800-53 Rev 5 Assessment, {ctrl['control_id']}: To assess this control, verify {ctrl['description'].lower()} Check parameters: {', '.join(ctrl['parameters']) if ctrl['parameters'] else 'none specified'}."
        for ctrl in catalog_data
    ] + high_baseline_data

    print(f"{Fore.CYAN}Building new vector store...{Style.RESET_ALL}")
    model, index, doc_list = build_vector_store(all_documents, args.model, KNOWLEDGE_DIR)

    print(f"{Fore.CYAN}Loading CCI-to-NIST mapping...{Style.RESET_ALL}")
    cci_to_nist = load_cci_mapping(os.path.join(KNOWLEDGE_DIR, 'U_CCI_List.xml'))

    print(f"{Fore.CYAN}Loading STIG data from folder: {stig_folder}{Style.RESET_ALL}")
    all_stig_recommendations, available_stigs = load_stig_data(stig_folder, cci_to_nist)
    logging.debug(f"Loaded {len(available_stigs)} STIGs: {[stig['file'] for stig in available_stigs]}")

    control_details = {ctrl['control_id']: ctrl for ctrl in catalog_data}
    high_baseline_controls = {normalize_control_id(entry.split(', ')[1].split(': ')[0]) for entry in high_baseline_data}

    print(f"{Fore.GREEN}Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog, 800-53A, and STIG Knowledge{Style.RESET_ALL}")
    print("Type 'help' for examples, 'list stigs' to see available STIGs, 'show unknown' to see unhandled queries, 'exit' to quit.\n")

    while True:
        print(f"{Fore.YELLOW}Enter your compliance question (e.g., 'How do I assess AU-3?', 'exit'):{Style.RESET_ALL}")
        query = input().strip()
        if query.lower() == 'exit':
            break
        if query.lower() == 'help':
            print("Examples:")
            print("- How should IA-5 be implemented for Windows?")
            print("- How do I assess AU-3?")
            print("- What is CCI-000130? (CCI lookup)")
            print("- List CCI mappings for AU-3 (Reverse CCI lookup)")
            print("- Show CCI mappings (CCI summary)")
            print("- List STIGs")
            print("- Show unknown (displays previously unhandled queries)")
            continue
        if query.lower() == 'show unknown':
            unknown_queries = load_unknown_queries()
            if unknown_queries:
                print(f"{Fore.CYAN}Previously unhandled queries:{Style.RESET_ALL}")
                for i, q in enumerate(unknown_queries, 1):
                    print(f"{i}. {q}")
            else:
                print("No unknown queries recorded yet.")
            continue
        if not query:
            print("Please enter a query or type 'help' for examples.")
            continue

        generate_checklist = False
        if "assess" in query.lower() or "audit" in query.lower():
            while True:
                checklist_response = input(f"{Fore.YELLOW}Generate an assessment checklist for this query? (y/n): {Style.RESET_ALL}").strip().lower()
                if checklist_response in ('y', 'n'):
                    generate_checklist = checklist_response == 'y'
                    break
                print("Please enter 'y' for yes or 'n' for no.")

        print(f"\n{Fore.CYAN}Processing...{Style.RESET_ALL}")
        retrieved_docs = retrieve_documents(query, model, index, doc_list)
        
        response = generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, cci_to_nist, generate_checklist=generate_checklist)
        
        if "Multiple STIG technologies available" in response:
            print(response)
            selected_idx = input().strip()
            if selected_idx.isdigit():
                selected_idx = int(selected_idx)
                response = generate_response(f"{query} with technology index {selected_idx}", retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, cci_to_nist, generate_checklist=generate_checklist)
        
        if "not found" in response.lower() or "no specific" in response.lower() or len(retrieved_docs) == 0:
            save_unknown_query(query)
            response += f"\n{Fore.YELLOW}Note: This query has been recorded for future improvement. Type 'show unknown' to see all recorded queries.{Style.RESET_ALL}"
        
        print(f"\n{Fore.CYAN}### Response to '{query}'{Style.RESET_ALL}\n{response}\n")

if __name__ == "__main__":
    main()
