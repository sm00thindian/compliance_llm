# src/parsers.py
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
    Extract NIST 800-53 controls from JSON data (OSCAL format).

    Args:
        json_data (dict): The JSON data containing control catalog information.

    Returns:
        list: A list of dictionaries with control details (id, title, description, parameters, related_controls).
    """
    controls = []
    if not json_data or 'catalog' not in json_data:
        logging.error("Invalid JSON structure: 'catalog' key missing.")
        return controls
    for group in json_data['catalog'].get('groups', []):
        for control in group.get('controls', []):
            control_id = control.get('id', '').upper()
            title = control.get('title', '')
            params = control.get('parameters', []) or []
            param_texts = [f"{param.get('id', '')}: {param.get('label', '')}" for param in params]
            description = " ".join(re.sub(r'\s+', ' ', part["prose"]).strip() for part in control.get('parts', []) if "prose" in part)
            related_controls = [link['href'].split('#')[-1].upper() for link in control.get('links', []) if link.get('rel') == 'related']
            controls.append({
                'control_id': control_id,
                'title': title,
                'description': description,
                'parameters': param_texts,
                'related_controls': related_controls
            })
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 JSON catalog.")
    return controls

def extract_high_baseline_controls(json_data):
    """
    Extract controls from NIST 800-53 Rev 5 High baseline JSON.

    Args:
        json_data (dict): The JSON data containing the high baseline profile.

    Returns:
        list: A list of strings representing controls in the high baseline.
    """
    controls = []
    if not json_data or 'profile' not in json_data:
        logging.error("Invalid JSON structure: 'profile' key missing.")
        return controls
    for import_ in json_data['profile'].get('imports', []):
        for include in import_.get('include-controls', []):
            control_id = include.get('with-ids', [''])[0].upper()
            if control_id:
                controls.append(f"NIST 800-53 Rev 5 High Baseline, {control_id}: Included in High baseline.")
    logging.info(f"Loaded {len(controls)} controls from NIST 800-53 Rev 5 High baseline.")
    return controls

def extract_assessment_procedures(json_data):
    """
    Extract assessment procedures from NIST SP 800-53A JSON.

    Args:
        json_data (dict): The JSON data containing assessment plan information.

    Returns:
        dict: A dictionary mapping control IDs to assessment methods.
    """
    assessments = {}
    if not json_data or 'assessment-plan' not in json_data:
        logging.error("Invalid JSON structure for 800-53A: 'assessment-plan' key missing.")
        return assessments
    for objective in json_data['assessment-plan'].get('objectives-and-methods', []):
        control_id = objective.get('target-id', '').upper()
        if control_id:
            methods = [m.get('description', '') for m in objective.get('assessment-methods', [])]
            assessments[control_id] = methods
    logging.info(f"Loaded {len(assessments)} assessment procedures from NIST SP 800-53A.")
    return assessments

def load_cci_mapping(cci_xml_path):
    """
    Load CCI-to-NIST control mappings from an XML file.

    Args:
        cci_xml_path (str): Path to the CCI XML file.

    Returns:
        dict: A dictionary mapping CCI IDs to NIST control IDs.
    """
    cci_to_nist = {}
    ns = {'cci': 'http://iase.disa.mil/cci'}
    try:
        tree = ET.parse(cci_xml_path)
        root = tree.getroot()
        for cci_item in root.findall('.//cci:cci_item', ns):
            cci_id = cci_item.get('id')
            rev5_control = next((ref.get('index') for ref in cci_item.findall('.//cci:reference', ns) if ref.get('title') == 'NIST SP 800-53 Revision 5'), None)
            if rev5_control:
                cci_to_nist[cci_id] = rev5_control
        logging.info(f"Loaded {len(cci_to_nist)} CCI-to-NIST mappings from XML")
    except Exception as e:
        logging.error(f"Failed to parse CCI XML: {e}")
        cci_to_nist = {
            'CCI-000196': 'IA-5',
            'CCI-000048': 'AC-7',
            'CCI-002450': 'SC-13',
            'CCI-000130': 'AU-3',
            'CCI-000366': 'CM-6',
            'CCI-001764': 'CM-7(5)'
        }
        logging.warning("Falling back to hardcoded CCI-to-NIST dictionary")
    return cci_to_nist

def parse_stig_xccdf(xccdf_data, cci_to_nist):
    """
    Parse STIG XCCDF file to extract rules and map to NIST controls via CCI.

    Args:
        xccdf_data (bytes): The raw XCCDF file content.
        cci_to_nist (dict): Mapping of CCI IDs to NIST control IDs.

    Returns:
        tuple: (stig_recommendations, technology, title, benchmark_id, version)
    """
    try:
        root = ET.fromstring(xccdf_data)
        ns = {'xccdf': root.tag.split('}')[0][1:]}
        logging.info(f"Using namespace: {ns['xccdf']}")
        
        title_elem = root.find('.//xccdf:title', ns)
        title = title_elem.text if title_elem is not None else "Untitled STIG"
        
        title_lower = title.lower()
        if "windows 10" in title_lower:
            technology = "Windows 10"
        elif "red hat enterprise linux 9" in title_lower:
            technology = "Red Hat 9"
        else:
            technology = title.split(' ')[0]
        
        benchmark_id = root.get('id', 'Unknown')
        version_elem = root.find('.//xccdf:version', ns)
        version = version_elem.text if version_elem is not None else "Unknown"
        
        fixtexts = {fix.get('fixref'): fix.text for fix in root.findall('.//xccdf:fixtext', ns) if fix.text}
        
        stig_recommendations = {}
        rules = root.findall('.//xccdf:Rule', ns)
        logging.info(f"Found {len(rules)} rules in STIG")
        
        for rule in rules:
            rule_id = rule.get('id')
            severity = rule.get('severity', 'medium')
            title_elem = rule.find('.//xccdf:title', ns)
            title_text = title_elem.text if title_elem is not None else "No title"
            fix_elem = rule.find('.//xccdf:fix', ns)
            fix_ref = fix_elem.get('id') if fix_elem is not None else None
            fix_text = fixtexts.get(fix_ref, "No fix instructions provided.") if fix_ref else "No fix instructions provided."
            
            ccis = rule.findall('.//xccdf:ident[@system="http://cyber.mil/cci"]', ns)
            for cci in ccis:
                cci_id = cci.text
                control_id = cci_to_nist.get(cci_id)
                if control_id:
                    if control_id not in stig_recommendations:
                        stig_recommendations[control_id] = []
                    if not any(rec['rule_id'] == rule_id for rec in stig_recommendations[control_id]):
                        stig_recommendations[control_id].append({
                            'rule_id': rule_id,
                            'title': title_text,
                            'fix': fix_text,
                            'severity': severity
                        })
                    logging.debug(f"Mapped {cci_id} to {control_id} for rule {rule_id}")
        
        logging.info(f"Parsed STIG data for {technology}: {len(stig_recommendations)} controls mapped")
        return stig_recommendations, technology, title, benchmark_id, version
    except Exception as e:
        logging.error(f"Failed to parse STIG XCCDF: {e}")
        raise

def load_stig_data(stig_folder, cci_to_nist):
    """
    Load STIG data from XCCDF files in the specified folder.

    Args:
        stig_folder (str): Directory containing STIG XCCDF files.
        cci_to_nist (dict): Mapping of CCI IDs to NIST control IDs.

    Returns:
        tuple: (all_stig_recommendations, available_stigs)
    """
    all_stig_recommendations = {}
    available_stigs = []
    stig_files = glob.glob(os.path.join(stig_folder, '*.xml'))
    logging.info(f"Found {len(stig_files)} STIG files in {stig_folder}")
    
    for stig_file in stig_files:
        try:
            with open(stig_file, 'rb') as f:
                xccdf_data = f.read()
            recommendations, technology, title, benchmark_id, version = parse_stig_xccdf(xccdf_data, cci_to_nist)
            all_stig_recommendations[technology] = recommendations
            available_stigs.append({
                'file': os.path.basename(stig_file),
                'title': title,
                'technology': technology,
                'benchmark_id': benchmark_id,
                'version': version
            })
            logging.info(f"Successfully loaded STIG: {os.path.basename(stig_file)}")
        except Exception as e:
            logging.error(f"Failed to load STIG file '{stig_file}': {e}")
    return all_stig_recommendations, available_stigs
