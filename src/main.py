# src/main.py
import argparse
import configparser
import logging
import os
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

def main():
    parser = argparse.ArgumentParser(description="NIST Compliance RAG Demo")
    parser.add_argument('--model', type=str, default='all-mpnet-base-v2', help='SentenceTransformer model name')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config/config.ini')
    stig_folder = config.get('DEFAULT', 'stig_folder', fallback='./stigs')
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
    cci_to_nist = load_cci_mapping('U_CCI_List.xml')

    print(f"{Fore.CYAN}Loading STIG data from folder: {stig_folder}{Style.RESET_ALL}")
    all_stig_recommendations, available_stigs = load_stig_data(stig_folder, cci_to_nist)

    control_details = {ctrl['control_id']: ctrl for ctrl in catalog_data}
    high_baseline_controls = {normalize_control_id(entry.split(', ')[1].split(': ')[0]) for entry in high_baseline_data}

    print(f"{Fore.GREEN}Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog, 800-53A, and STIG Knowledge{Style.RESET_ALL}")
    print("Type 'help' for examples, 'list stigs' to see available STIGs, 'exit' to quit.\n")

    while True:
        query = input(f"{Fore.YELLOW}Enter your compliance question (e.g., 'How do I assess AU-3?', 'exit'):{Style.RESET_ALL}").strip()
        if query.lower() == 'exit':
            break
        if query.lower() == 'help':
            print("Examples:")
            print("- How should IA-5 be implemented for Windows?")
            print("- How do I assess AU-3?")
            print("- List STIGs")
            continue
        if not query:
            continue

        generate_checklist = False
        selected_tech = None
        
        # Checklist and STIG technology prompt for assessment queries
        if "assess" in query.lower() or "audit" in query.lower():
            if "for" not in query.lower():
                available_techs = list(all_stig_recommendations.keys())
                if available_techs:
                    print(f"{Fore.YELLOW}Multiple STIG technologies available:{Style.RESET_ALL}")
                    for i, tech in enumerate(available_techs, 1):
                        print(f"  {i}. {tech}")
                    while True:
                        try:
                            choice = input(f"{Fore.YELLOW}Select a technology (1-{len(available_techs)}, or 0 for all): {Style.RESET_ALL}").strip()
                            choice = int(choice)
                            if 0 <= choice <= len(available_techs):
                                selected_tech = available_techs[choice - 1] if choice > 0 else None
                                break
                            print(f"Please enter a number between 0 and {len(available_techs)}.")
                        except ValueError:
                            print("Invalid input. Please enter a number.")
            while True:
                checklist_response = input(f"{Fore.YELLOW}Generate an assessment checklist for this query? (y/n): {Style.RESET_ALL}").strip().lower()
                if checklist_response in ('y', 'n'):
                    generate_checklist = checklist_response == 'y'
                    break
                print("Please enter 'y' for yes or 'n' for no.")
        
        # STIG technology prompt for implementation queries without system type
        if "implement" in query.lower() and "for" not in query.lower():
            available_techs = list(all_stig_recommendations.keys())
            if available_techs:
                print(f"{Fore.YELLOW}Multiple STIG technologies available:{Style.RESET_ALL}")
                for i, tech in enumerate(available_techs, 1):
                    print(f"  {i}. {tech}")
                while True:
                    try:
                        choice = input(f"{Fore.YELLOW}Select a technology (1-{len(available_techs)}, or 0 for all): {Style.RESET_ALL}").strip()
                        choice = int(choice)
                        if 0 <= choice <= len(available_techs):
                            selected_tech = available_techs[choice - 1] if choice > 0 else None
                            break
                        print(f"Please enter a number between 0 and {len(available_techs)}.")
                    except ValueError:
                        print("Invalid input. Please enter a number.")

        print(f"\n{Fore.CYAN}Processing...{Style.RESET_ALL}")
        retrieved_docs = retrieve_documents(query, model, index, doc_list)
        response = generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, generate_checklist, selected_tech)
        print(f"\n{Fore.CYAN}### Response to '{query}'{Style.RESET_ALL}\n{response}\n")

if __name__ == "__main__":
    main()
