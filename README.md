# NIST Compliance RAG Explorer

This repository hosts a Retrieval-Augmented Generation (RAG) tool designed to simplify interaction with NIST 800-53 Revision 5 compliance materials. It aggregates the NIST 800-53 Rev 5 Catalog, 800-53A Rev 5 Assessment Procedures, High Baseline, and Supplemental Guidance into a searchable database, enabling users to ask detailed questions about compliance controls, such as implementation guidance, required evidence, mitigated risks, and inter-control relationships.

## Highlights
- Pulls and caches NIST 800-53 Rev 5 data from official sources.
- Employs SentenceTransformers to create a vector store for fast document retrieval.
- Handles queries like:
  - "How should AU-2 be implemented?"
  - "What evidence is needed for CA-7?"
  - "What risks does AC-1 mitigate?"
  - "How does SI-4 relate to SI-7?"
- Offers an interactive CLI with configurable model options.

## Requirements
- Python 3.8 or higher
- Git (to clone the repo)
- Internet access (for initial data download)

## Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/sm00thindian/nist-compliance-rag-explorer.git
   cd nist-compliance-rag-explorer
   ```

2. **Configure the Environment**:
   - Create a `config.ini` file with these settings:
     ```ini
     [DEFAULT]
     catalog_url = https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json
     assessment_url = https://csrc.nist.gov/files/pubs/sp/800/53/a/r5/final/docs/sp800-53ar5-assessment-procedures.txt
     high_baseline_url = https://raw.githubusercontent.com/usnistgov/oscal-content/refs/heads/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_HIGH-baseline-resolved-profile_catalog.json
     nist_800_53_pdf_url = https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf
     vector_file = vector_store_all_controls.faiss
     docs_file = documents_all_controls.pkl
     hash_file = data_hash_all_controls.txt
     ```

3. **Run the Setup Script**:
   - Use `setup_and_run_nist_demo.py` to configure a virtual environment, install dependencies, and start the demo:
   ```bash
   python3 setup_and_run_nist_demo.py
   ```
   - Select a model when prompted (e.g., `2` for `all-mpnet-base-v2`).

## Dependencies
Specified in `requirements.txt`:
- `requests`
- `sentence-transformers`
- `faiss-cpu`
- `numpy`
- `pdfplumber`
- `tqdm`

The setup script installs these automatically.

## How to Use
1. Once installed, the demo launches with:
   ```
   Welcome to the Compliance RAG Demo with NIST 800-53 Rev 5 Catalog, 800-53A Rev 5 Assessment, High Baseline, and Supplemental Guidance Knowledge (Version 2.27)
   Type 'help' for examples, 'exit' to quit.
   ```
2. Input a compliance-related question (e.g., "What risks does AC-3 mitigate?").
3. Review the response, which may include control details, implementation steps, evidence needs, risk info, or control relationships.
4. Type `exit` to close the demo.

## Project Structure
- `nist_compliance_rag.py`: Main script for data processing, vector store creation, and query handling.
- `setup_and_run_nist_demo.py`: Automates environment setup and demo execution.
- `config.ini`: Defines NIST data sources and file paths.
- `requirements.txt`: Python package dependencies.
- `debug.log`: Runtime log file (regenerated each run).

## Available Models
Select one of these SentenceTransformer models during setup:
1. `all-MiniLM-L12-v2`: Quick and light, ideal for testing.
2. `all-mpnet-base-v2`: Well-rounded, recommended default.
3. `multi-qa-MiniLM-L6-cos-v1`: Tailored for Q&A, fast but less nuanced.
4. `all-distilroberta-v1`: Accurate, moderately paced.
5. `paraphrase-MiniLM-L6-v2`: Lightweight, great for rephrasing.
6. `all-roberta-large-v1`: Top accuracy, resource-heavy.

## Troubleshooting
- **Data Fetch Issues**: Verify `config.ini` URLs are valid and reachable.
- **Sparse Responses**: Inspect `debug.log` for retrieved documents; consider increasing retrieval limit in `nist_compliance_rag.py`.
- **Setup Errors**: Ensure Python version compatibility and dependency installation success.

## Contributing
Contributions are welcome! Open issues or submit pull requests to enhance features, fix bugs, or optimize performance.

## License
This project is licensed under the Apache License 2.0. See the `LICENSE` file for details.
