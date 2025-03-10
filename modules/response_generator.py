import re
from modules.utils import normalize_control_id
import logging

def retrieve_documents(query, model, index, doc_list, top_k=100):
    query_embedding = model.encode([query])
    distances, indices = index.search(query_embedding, top_k)
    retrieved_docs = [doc_list[idx] for idx in indices[0]]
    logging.info(f"Retrieved {len(retrieved_docs)} documents for query")
    return retrieved_docs

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs):
    # Your code to generate a response based on the query and retrieved documents
    pass
