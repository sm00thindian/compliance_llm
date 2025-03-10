import os
import subprocess
import sys

# Define the virtual environment directory
VENV_DIR = "venv"

def create_virtual_env():
    """Create a virtual environment if it doesn't exist."""
    if not os.path.exists(VENV_DIR):
        print(f"Creating virtual environment in {VENV_DIR}...")
        subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)
    else:
        print(f"Virtual environment already exists in {VENV_DIR}.")

def get_python_cmd():
    """Get the Python executable path from the virtual environment."""
    if sys.platform == "win32":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")

def install_requirements():
    """Install dependencies from requirements.txt in the virtual environment."""
    requirements_file = "requirements.txt"
    python_cmd = get_python_cmd()

    if not os.path.exists(requirements_file):
        print(f"Error: {requirements_file} not found. Creating it with default dependencies.")
        with open(requirements_file, 'w') as f:
            f.write("requests\nsentence-transformers\nfaiss-cpu\nnumpy\npdfplumber\ntqdm\n")
    
    print("Installing dependencies from requirements.txt...")
    try:
        subprocess.run([python_cmd, "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([python_cmd, "-m", "pip", "install", "-r", requirements_file], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error installing dependencies: {e}")
        sys.exit(1)

def download_cci_xml():
    """Download and extract U_CCI_List.xml using the virtual environment's Python."""
    cci_file = "U_CCI_List.xml"
    python_cmd = get_python_cmd()

    if os.path.exists(cci_file):
        print(f"{cci_file} already exists. Skipping download.")
        return

    print("Downloading CCI XML using virtual environment Python...")
    download_script = """
import requests
import zipfile
import os

cci_file = "U_CCI_List.xml"
cci_zip_url = "https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_CCI_List.zip"
cci_zip_file = "U_CCI_List.zip"

print(f"Downloading CCI XML from {cci_zip_url}...")
response = requests.get(cci_zip_url, stream=True)
response.raise_for_status()
with open(cci_zip_file, 'wb') as f:
    for chunk in response.iter_content(chunk_size=8192):
        f.write(chunk)

with zipfile.ZipFile(cci_zip_file, 'r') as zip_ref:
    zip_ref.extract(cci_file)
    print(f"Extracted {cci_file} from {cci_zip_file}")

os.remove(cci_zip_file)
print(f"Removed temporary file {cci_zip_file}")
"""
    with open("download_cci.py", "w") as f:
        f.write(download_script)
    
    try:
        subprocess.run([python_cmd, "download_cci.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to download CCI XML: {e}")
        print("Proceeding with fallback CCI mapping in main.py.")
    finally:
        if os.path.exists("download_cci.py"):
            os.remove("download_cci.py")

def run_demo(selected_model):
    """Run the main.py script with the selected model."""
    python_cmd = get_python_cmd()
    try:
        subprocess.run([python_cmd, 'main.py', '--model', selected_model], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running nist_compliance_rag.py: {e}")
        sys.exit(1)

def main():
    """Main function to set up the environment, install dependencies, and run the demo."""
    models = [
        ("all-MiniLM-L12-v2", "Fast and lightweight (12 layers). Great for quick testing, but less accurate on complex queries."),
        ("all-mpnet-base-v2", "Balanced performance and speed. Strong general-purpose model, recommended for most use cases."),
        ("multi-qa-MiniLM-L6-cos-v1", "Optimized for question-answering (6 layers). Fast, but may miss nuanced relationships."),
        ("all-distilroberta-v1", "Distilled RoBERTa model. Good accuracy, slower than MiniLM, but better for detailed text."),
        ("paraphrase-MiniLM-L6-v2", "Lightweight (6 layers), excels at paraphrasing. Fast, but less robust for technical queries."),
        ("all-roberta-large-v1", "High accuracy, large model. Best for complex queries, but slowest and memory-intensive.")
    ]

    print("Select a model to test:")
    for i, (model_name, description) in enumerate(models, 1):
        print(f"{i}: {model_name}\n   - {description}")
    
    while True:
        try:
            choice = int(input("Enter the number of the model you want to test (1-6): "))
            if 1 <= choice <= 6:
                break
            print("Please enter a number between 1 and 6.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    selected_model = models[choice - 1][0]
    print(f"Setting up and running main.py with model: {selected_model}")

    # Setup steps
    create_virtual_env()
    install_requirements()
    download_cci_xml()

    # Run the demo
    run_demo(selected_model)

if __name__ == "__main__":
    main()
