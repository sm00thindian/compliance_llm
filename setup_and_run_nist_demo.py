import os
import shutil
import subprocess
import sys

def clear_demo_environment():
    print("Clearing demo environment...")
    files_to_remove = [
        'catalog_cache.json', 'assessment_cache.txt', 'high_baseline_cache.json',
        'nist_800_53_r5.pdf', 'vector_store_all_controls.faiss',
        'documents_all_controls.pkl', 'data_hash_all_controls.txt', 'debug.log'
    ]
    for file in files_to_remove:
        if os.path.exists(file):
            os.remove(file)
            print(f"Removed {file}")
    
    venv_dir = 'venv'
    if os.path.exists(venv_dir):
        shutil.rmtree(venv_dir)
        print("Removed virtual environment")
    print("Demo environment cleared.")

def setup_virtual_environment():
    print("Setting up virtual environment...")
    subprocess.run([sys.executable, '-m', 'venv', 'venv'], check=True)
    print("Virtual environment created.")
    
    print("Installing requirements from requirements.txt...")
    pip_cmd = os.path.join('venv', 'Scripts' if os.name == 'nt' else 'bin', 'pip')
    subprocess.run([pip_cmd, 'install', '-r', 'requirements.txt'], check=True)
    print("Requirements installed.")

def run_demo(model_name):
    print(f"Running nist_compliance_rag.py with model: {model_name}")
    python_cmd = os.path.join('venv', 'Scripts' if os.name == 'nt' else 'bin', 'python')
    subprocess.run([python_cmd, 'nist_compliance_rag.py', '--model', model_name], check=True)

def main():
    print("NIST Compliance RAG Demo Setup and Runner")
    print("=" * 41)
    
    clear_demo_environment()
    setup_virtual_environment()
    
    models = [
        ("all-MiniLM-L12-v2", 
         "Fast and lightweight (12 layers). Great for quick testing, but less accurate on complex queries."),
        ("all-mpnet-base-v2", 
         "Balanced performance and speed. Strong general-purpose model, recommended for most use cases."),
        ("multi-qa-MiniLM-L6-cos-v1", 
         "Optimized for question-answering (6 layers). Fast, but may miss nuanced relationships."),
        ("all-distilroberta-v1", 
         "Distilled RoBERTa model. Good accuracy, slower than MiniLM, but better for detailed text."),
        ("paraphrase-MiniLM-L6-v2", 
         "Lightweight (6 layers), excels at paraphrasing. Fast, but less robust for technical queries."),
        ("all-roberta-large-v1", 
         "High accuracy, large model. Best for complex queries, but slowest and memory-intensive.")
    ]
    
    print("\nSelect a model to test:")
    for i, (model_name, description) in enumerate(models, 1):
        print(f"{i}: {model_name}")
        print(f"   - {description}")
    
    while True:
        try:
            choice = int(input("Enter the number of the model you want to test (1-6): "))
            if 1 <= choice <= 6:
                break
            print("Please enter a number between 1 and 6.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    selected_model = models[choice - 1][0]
    run_demo(selected_model)

if __name__ == "__main__":
    main()
