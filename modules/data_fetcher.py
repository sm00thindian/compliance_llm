import requests
import io
import logging

def fetch_json_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Fetched data from {url}")
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch JSON data from {url}: {e}")
        return None

def fetch_pdf_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Fetched data from {url}")
        return io.BytesIO(response.content)
    except requests.RequestException as e:
        logging.error(f"Failed to fetch PDF data from {url}: {e}")
        return None
