import argparse
import configparser
import logging
import os
from colorama import init, Fore, Style
from .data_fetchers import fetch_json_data, fetch_excel_data
from .parsers import (
    extract_controls_from_json, extract_controls_from_excel,
    normalize_control_id
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
    """
    Main entry point for the NIST Compliance RAG Demo.

    This function handles the entire workflow: fetching data, building the vector store,
    loading mappings, and processing user queries interactively.

    Usage:
        python -m src.main --model all-mpnet-base-v2
    """
    parser = argparse.ArgumentParser(description="NIST Compliance RAG Demo")
    parser.add_argument('--model', type=str, default='all-mpnet-base-v2', help='SentenceTransformer model name')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config/config.ini')
    nist_800_53_xls_url = config.get('DEFAULT', 'nist_800_53_xls_url')
    catalog_url = config.get('DEFAULT', 'catalog_url')
    excel_local_path = os.path.join(KNOWLEDGE_DIR, 'sp800-53r5-control-catalog.xlsx')

    print(f"{Fore.CYAN}Fetching NIST SP 800-53 Rev 5 catalog data...{Style.RESET_ALL}")
    catalog_json = fetch_json_data(catalog_url)
    catalog_data = extract_controls_from_json(catalog_json) if catalog_json else extract_controls_from_excel(fetch_excel_data(nist_800_53_xls_url, excel_local_path))

    all_documents = [
        f"NIST 800-53 Rev 5 Catalog, {ctrl['control_id']}: {ctrl['title']} {ctrl['description']}"
        for ctrl in catalog_data
    ]

    print(f"{Fore.CYAN}Building new vector store...{Style.RESET_ALL}")
    model, index, doc_list = build_vector_store(all_documents, args.model, KNOWLEDGE_DIR)

    control_details = {ctrl['control_id']: ctrl for ctrl in catalog_data}

    print(f"{Fore.GREEN}Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog{Style.RESET_ALL}")
    print("Type 'exit' to quit.\n")

    while True:
        print(f"{Fore.YELLOW}Enter your compliance question (e.g., 'How do I assess AU-3?', 'exit'):{Style.RESET_ALL}")
        query = input().strip()
        if query.lower() == 'exit':
            break
        if not query:
            print("Please enter a query.")
            continue

        print(f"\n{Fore.CYAN}Processing...{Style.RESET_ALL}")
        retrieved_docs = retrieve_documents(query, model, index, doc_list)
        response = generate_response(query, retrieved_docs, control_details, {}, {}, [], {})
        print(f"\n{Fore.CYAN}### Response to '{query}'{Style.RESET_ALL}\n{response}\n")

if __name__ == "__main__":
    main()
