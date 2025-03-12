import re
import os
import pandas as pd
import xml.etree.ElementTree as ET
import logging
import glob

def normalize_control_id(control_id):
    """
    Normalize a NIST control ID by removing leading zeros and preserving enhancements.

    Args:
        control_id (str): The control ID to normalize (e.g., 'AC-01', 'CM-7(5)').

    Returns:
        str: The normalized control ID (e.g., 'AC-1', 'CM-7(5)').

    Example:
        >>> normalize_control_id('AC-01')
        'AC-1'
        >>> normalize_control_id('CM-7(5)')
        'CM-7(5)'
    """
    match = re.match(r'^([A-Z]{2})-0*([0-9]+)(?:\(([a-z0-9]+)\))?$', control_id)
    if match:
        family, number, enhancement = match.groups()
        return f"{family}-{number}" + (f"({enhancement})" if enhancement else "")
    return control_id

def extract_controls_from_excel(excel_file):
    """
    Extract NIST 800-53 controls from an Excel file.

    Args:
        excel_file (str or BytesIO): Path to the Excel file or a file-like object.

    Returns:
        list: A list of dictionaries, each containing control details (id, title, description, parameters, related_controls).

    Example:
        >>> controls = extract_controls_from_excel('sp800-53r5-control-catalog.xlsx')
        >>> print(controls[0]['control_id'])
        'AC-1'
    """
    controls = []
    df = pd.read_excel(excel_file, sheet_name='SP 800-53 Revision 5', header=None, skiprows=1)
    for _, row in df.iterrows():
        control_id = str(row[0]).upper()
        if not re.match(r'[A-Z]{2}-[0-9]+', control_id):
            continue
        controls.append({
            'control_id': control_id,
            'title': str(row[1]),
            'description': str(row[2]),
            'parameters': [],
            'related_controls': [normalize_control_id(ctrl.upper()) for ctrl in str(row[4]).split(', ') if ctrl.strip()] if pd.notna(row[4]) else []
        })
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 Excel catalog.")
    return controls

def extract_controls_from_json(json_data):
    """
    Extract NIST 800-53 controls from JSON data.

    Args:
        json_data (dict): The JSON data containing control catalog information.

    Returns:
        list: A list of dictionaries with control details (id, title, description, parameters, related_controls).

    Example:
        >>> controls = extract_controls_from_json({'controls': [{'id': 'AC-1', 'title': 'Access Control Policy', 'description': 'Desc'}]})
        >>> print(controls[0]['control_id'])
        'AC-1'
    """
    controls = []
    for control in json_data.get('controls', []):
        controls.append({
            'control_id': control['id'],
            'title': control['title'],
            'description': control.get('description', ''),
            'parameters': control.get('parameters', []),
            'related_controls': control.get('related_controls', [])
        })
    logging.info(f"Extracted {len(controls)} controls from JSON data.")
    return controls

# Add similar docstrings to other functions like extract_high_baseline_controls, extract_assessment_procedures, etc.
