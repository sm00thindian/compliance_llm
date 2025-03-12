import os
import hashlib
import pickle
import logging
from sentence_transformers import SentenceTransformer
import faiss
import re
from .parsers import normalize_control_id

def build_vector_store(documents, model_name, knowledge_dir):
    """
    Build or load a FAISS vector store from a list of documents.

    Args:
        documents (list): List of strings representing the documents.
        model_name (str): Name of the SentenceTransformer model to use.
        knowledge_dir (str): Directory to save or load the FAISS index.

    Returns:
        tuple: (model, index, doc_list)
            - model: The SentenceTransformer model.
            - index: The FAISS index.
            - doc_list: The list of documents.

    Example:
        >>> model, index, doc_list = build_vector_store(['doc1', 'doc2'], 'all-mpnet-base-v2', 'knowledge')
    """
    index_file = os.path.join(knowledge_dir, f"faiss_index_{hashlib.md5(model_name.encode()).hexdigest()}.pkl")
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
    return model, index, doc_list

def retrieve_documents(query, model, index, doc_list, top_k=100):
    """
    Retrieve the top-k most relevant documents for a given query.

    Args:
        query (str): The query string.
        model (SentenceTransformer): The SentenceTransformer model.
        index (faiss.Index): The FAISS index.
        doc_list (list): The list of documents.
        top_k (int, optional): Number of documents to retrieve. Defaults to 100.

    Returns:
        list: The top-k relevant documents.

    Example:
        >>> retrieved = retrieve_documents('How to implement AC-1?', model, index, doc_list)
        >>> print(len(retrieved))
        100
    """
    query_embedding = model.encode([query])
    distances, indices = index.search(query_embedding, top_k)
    retrieved_docs = [doc_list[idx] for idx in indices[0]]
    # Filter for exact control ID match if present in query
    control_match = re.search(r'(\w{2}-\d+(?:\([a-z0-9]+\))?)', query, re.IGNORECASE)
    if control_match:
        control_id = normalize_control_id(control_match.group(1).upper())
        retrieved_docs = [doc for doc in retrieved_docs if control_id in doc] or retrieved_docs[:5]  # Fallback to top 5 if no exact match
    logging.info(f"Retrieved {len(retrieved_docs)} documents for query")
    return retrieved_docs
