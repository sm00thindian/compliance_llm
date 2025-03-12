import os
import requests
import logging
from io import BytesIO

def fetch_json_data(url):
    """
    Fetch JSON data from a given URL.

    Args:
        url (str): The URL to fetch JSON data from.

    Returns:
        dict or None: The JSON data as a dictionary, or None if fetching fails.

    Example:
        >>> data = fetch_json_data('https://example.com/data.json')
        >>> print(data.keys())
        dict_keys(['key1', 'key2'])
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Fetched data from {url}")
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch JSON data from {url}: {e}")
        return None

def fetch_excel_data(url, local_path):
    """
    Fetch Excel data from a URL if not already present locally.

    Args:
        url (str): The URL to fetch the Excel file from.
        local_path (str): The local path to save or load the Excel file.

    Returns:
        BytesIO or None: A file-like object containing the Excel data, or None if fetching fails.

    Example:
        >>> excel_data = fetch_excel_data('https://example.com/data.xlsx', 'local_data.xlsx')
        >>> df = pd.read_excel(excel_data)
    """
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
