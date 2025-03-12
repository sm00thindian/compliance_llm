# src/vector_store.py
import os
import hashlib
import pickle
import logging
from sentence_transformers import SentenceTransformer
import faiss

def build_vector_store(documents, model_name, knowledge_dir):
    """Build or load a FAISS vector store from documents."""
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
    """Retrieve top-k relevant documents for a query."""
    query_embedding = model.encode([query])
    distances, indices = index.search(query_embedding, top_k)
    retrieved_docs = [doc_list[idx] for idx in indices[0]]
    logging.info(f"Retrieved {len(retrieved_docs)} documents for query")
    return retrieved_docs
