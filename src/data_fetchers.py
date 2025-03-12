# src/data_fetchers.py
import os
import requests
import logging
from io import BytesIO

def fetch_json_data(url):
    """Fetch JSON data from a URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Fetched data from {url}")
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch JSON data from {url}: {e}")
        return None

def fetch_excel_data(url, local_path):
    """Fetch Excel data from a URL if not already present locally."""
    if os.path.exists(local_path):
        logging.info(f"Using existing Excel file at {local_path}")
        with open(local_path, 'rb') as f:
            return BytesIO(f.read())
    else:
        try:
            response = requests.get(url)
            response.raise_for_status()
            with open(local_path, 'wb') as f:
                f.write(response.content)
            logging.info(f"Downloaded Excel data from {url} to {local_path}")
            return BytesIO(response.content)
        except requests.RequestException as e:
            logging.error(f"Failed to fetch Excel data from {url}: {e}")
            return None
