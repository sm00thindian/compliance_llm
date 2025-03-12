import re
import csv
import os
from datetime import datetime
from colorama import Fore, Style
from .text_processing import extract_actionable_steps

def save_checklist(control_id, steps, stig_recommendations, filename_prefix="checklist"):
    """
    Save assessment steps and STIG recommendations as a CSV checklist.

    Args:
        control_id (str): The control ID (e.g., 'AC-1').
        steps (list): List of assessment steps.
        stig_recommendations (dict): STIG recommendations grouped by technology.
        filename_prefix (str, optional): Prefix for the checklist filename. Defaults to "checklist".

    Returns:
        str: The path to the saved checklist CSV file.

    Example:
        >>> filename = save_checklist('AC-1', ['Verify access control'], {'Windows': [{'rule_id': 'WN10-00-000010', 'title': 'Example', 'fix': 'Fix text'}]})
        >>> print(filename)
        'assessment_checklists/checklist_AC-1_20231017_123456.csv'
    """
    checklist_dir = "assessment_checklists"
    os.makedirs(checklist_dir, exist_ok=True)
    filename = os.path.join(checklist_dir, f"{filename_prefix}_{control_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Step", "Description", "Severity", "Evidence", "Status"])
        for step in steps:
            writer.writerow([f"NIST {control_id}", f"Verify {control_id}", step, "N/A", "", "Pending"])
        for tech, recs in stig_recommendations.items():
            for matched_control, rec_list in recs.items():
                for rec in rec_list:
                    writer.writerow([f"STIG {tech}", rec['rule_id'], rec['fix'], rec.get('severity', 'medium').capitalize(), "", "Pending"])
    return filename

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, stig_recommendations, available_stigs, assessment_procedures, generate_checklist=False):
    """
    Generate a response to a user query based on retrieved documents and compliance data.

    Args:
        query (str): The user's query (e.g., 'How do I assess AU-3?').
        retrieved_docs (list): List of retrieved documents relevant to the query.
        control_details (dict): Dictionary mapping control IDs to their details.
        high_baseline_controls (set): Set of control IDs in the high baseline.
        stig_recommendations (dict): STIG recommendations grouped by technology.
        available_stigs (list): List of available STIGs.
        assessment_procedures (dict): Assessment procedures for controls.
        generate_checklist (bool, optional): Whether to generate a checklist. Defaults to False.

    Returns:
        str: A formatted response to the query.

    Example:
        >>> response = generate_response('How do I assess AU-3?', ['doc1'], {'AU-3': {'title': 'Audit'}}, set(), {}, [], {})
        >>> print(response)
        'Control AU-3: Audit...'
    """
    control_id_match = re.search(r'[A-Z]{2}-[0-9]+(?:\([a-z0-9]+\))?', query)
    if control_id_match:
        control_id = control_id_match.group(0)
        if control_id in control_details:
            ctrl = control_details[control_id]
            response = f"Control {control_id}: {ctrl['title']}\nDescription: {ctrl['description']}"
            if generate_checklist:
                steps = extract_actionable_steps(ctrl['description'])
                filename = save_checklist(control_id, steps, stig_recommendations)
                response += f"\nChecklist saved to: {filename}"
            return response
    return "Relevant info: " + "\n".join(retrieved_docs[:5])
