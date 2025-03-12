import os
import subprocess
import sys
import shutil
import configparser

VENV_DIR = "venv"
PYTHON_312 = "/opt/homebrew/bin/python3.12"
KNOWLEDGE_DIR = "knowledge"

def check_python_binary():
    if not os.path.exists(PYTHON_312):
        print(f"Error: {PYTHON_312} not found. Install Python 3.12 via Homebrew: 'brew install python@3.12'")
        sys.exit(1)
    print(f"Using Python 3.12 at {PYTHON_312}")

def create_virtual_env():
    if not os.path.exists(VENV_DIR):
        print(f"Creating virtual environment in {VENV_DIR}...")
        subprocess.run([PYTHON_312, "-m", "venv", VENV_DIR], check=True)
    else:
        print(f"Virtual environment already exists in {VENV_DIR}.")

def get_python_cmd():
    return os.path.join(VENV_DIR, "bin", "python") if sys.platform != "win32" else os.path.join(VENV_DIR, "Scripts", "python.exe")

def install_requirements():
    python_cmd = get_python_cmd()
    if not os.path.exists("requirements.txt"):
        print("Error: requirements.txt not found.")
        sys.exit(1)
    
    print("Installing dependencies...")
    print("  Step 1/3: Upgrading pip...", end=" ", flush=True)
    subprocess.run([python_cmd, "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=True)
    print("complete")

    print("  Step 2/3: Installing requirements from requirements.txt...", end=" ", flush=True)
    subprocess.run([python_cmd, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"], check=True)
    print("complete")

    print("  Step 3/3: Downloading spaCy model...", end=" ", flush=True)
    subprocess.run([python_cmd, "-m", "spacy", "download", "en_core_web_sm", "--quiet"], check=True)
    print("complete")

def download_cci_xml():
    python_cmd = get_python_cmd()
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    cci_file = os.path.join(KNOWLEDGE_DIR, "U_CCI_List.xml")
    config = configparser.ConfigParser()
    config.read('config/config.ini')
    cci_url = config.get('DEFAULT', 'cci_url', fallback='https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_CCI_List.zip')
    if os.path.exists(cci_file):
        print(f"{cci_file} already exists.")
        return
    print("Downloading CCI XML...")
    subprocess.run([python_cmd, "-c", f"""
import requests, zipfile, os
url = '{cci_url}'
r = requests.get(url, stream=True); r.raise_for_status()
with open('U_CCI_List.zip', 'wb') as f:
    for chunk in r.iter_content(8192): f.write(chunk)
with zipfile.ZipFile('U_CCI_List.zip', 'r') as z: z.extract('U_CCI_List.xml')
os.rename('U_CCI_List.xml', '{cci_file}')
os.remove('U_CCI_List.zip')
print('Downloaded and extracted U_CCI_List.xml to {cci_file}')
"""], check=True)

def run_demo(selected_model):
    python_cmd = get_python_cmd()
    subprocess.run([python_cmd, "-m", "src.main", "--model", selected_model], check=True, cwd=os.path.dirname(os.path.abspath(__file__)))

def main():
    check_python_binary()
    models = [
        ("all-MiniLM-L12-v2", "Fast, lightweight (12 layers)."),
        ("all-mpnet-base-v2", "Balanced performance and speed (default)."),
        ("multi-qa-MiniLM-L6-cos-v1", "Optimized for QA (6 layers)."),
        ("all-distilroberta-v1", "Distilled RoBERTa, good accuracy."),
        ("paraphrase-MiniLM-L6-v2", "Lightweight, excels at paraphrasing."),
        ("all-roberta-large-v1", "High accuracy, memory-intensive.")
    ]
    print("Select a model:")
    for i, (name, desc) in enumerate(models, 1):
        print(f"{i}: {name} - {desc}")
    while True:
        try:
            choice = int(input("Enter number (1-6): "))
            if 1 <= choice <= len(models):
                break
            print(f"Please enter a number between 1 and {len(models)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    selected_model = models[choice - 1][0]
    print(f"Selected model: {selected_model}")

    create_virtual_env()
    install_requirements()
    download_cci_xml()
    run_demo(selected_model)

if __name__ == "__main__":
    main()
