# src/response_generator.py
import re
import csv
import os
from datetime import datetime
from colorama import Fore, Style
from .text_processing import extract_actionable_steps

def save_checklist(control_id, steps, stig_recommendations, filename_prefix="checklist"):
    """Save assessment steps and STIG recommendations as a CSV checklist."""
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

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, generate_checklist=False, selected_tech=None):
    """Generate a detailed, user-friendly response for NIST 800-53 queries."""
    query_lower = query.lower()
    response = []

    severity_colors = {
        'High': Fore.RED,
        'Medium': Fore.YELLOW,
        'Low': Fore.GREEN
    }

    # Handle "list stigs" queries
    if "list stigs" in query_lower:
        keyword = query_lower.split("for")[1].strip() if "for" in query_lower else None
        filtered_stigs = [
            stig for stig in available_stigs 
            if not keyword or keyword.lower() in stig['technology'].lower() or keyword.lower() in stig['title'].lower()
        ]
        if not filtered_stigs:
            return f"No STIGs found{' for ' + keyword if keyword else ''}. Check `stig_folder` in `config.ini`."
        
        response.append(f"{Fore.CYAN}### Available STIGs{Style.RESET_ALL}")
        response.append("Here’s a list of STIGs loaded in the system:\n")
        response.append("+------------------------------------+----------------------+--------------+---------+")
        response.append("| File Name                          | Title                | Technology   | Version |")
        response.append("+------------------------------------+----------------------+--------------+---------+")
        for stig in filtered_stigs:
            short_title = stig['technology'] + " STIG"
            response.append(f"| {stig['file']:<34} | {short_title:<20} | {stig['technology']:<12} | {stig['version']:<7} |")
            response.append("+------------------------------------+----------------------+--------------+---------+")
        return "\n".join(response)

    # Extract control IDs and system type
    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2}(?:\s*\([a-zA-Z0-9]+\))?)\b')
    control_ids = [match.replace(' ', '') for match in control_pattern.findall(query.upper())]
    system_match = re.search(r'for\s+([Windows|Linux|Red Hat|Ubuntu|macOS|Cisco].*?)(?:\s|$)', query, re.IGNORECASE)
    system_type = system_match.group(1).strip().rstrip('?') if system_match else selected_tech

    if not control_ids:
        response.append(f"{Fore.RED}**No NIST controls detected.**{Style.RESET_ALL} Try including a control ID like 'AU-3'.")
        return "\n\n".join(response)

    response.append(f"{Fore.YELLOW}**Controls Covered:** {', '.join(control_ids)}{Style.RESET_ALL}" + (f" for {system_type}" if system_type else ""))

    is_assessment_query = "assess" in query_lower or "audit" in query_lower
    is_implementation_query = "implement" in query_lower
    is_info_query = query_lower.startswith("what is")

    for control_id in control_ids:
        if control_id not in control_details:
            response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
            response.append(f"- **Status:** Not found in the catalog.")
            continue

        ctrl = control_details[control_id]
        response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
        response.append(f"- **Title:** {ctrl['title']}")
        response.append(f"- **Description:** {ctrl['description']}")
        response.append(f"- **Related Controls:** {', '.join(ctrl.get('related_controls', [])) if ctrl.get('related_controls', []) else 'None'}")
        response.append("")  # Carriage return after control details

        if is_assessment_query:
            response.append(f"{Fore.CYAN}#### Assessing {control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            response.append(f"{Fore.WHITE}This control ensures {ctrl['title'].lower()}. Assessing it verifies compliance with security policies.{Style.RESET_ALL}")
            response.append("---")

            if control_id in assessment_procedures:
                response.append(f"{Fore.CYAN}NIST SP 800-53A Assessment Steps:{Style.RESET_ALL}")
                for i, method in enumerate(assessment_procedures[control_id], 1):
                    response.append(f"  {i}. {Fore.GREEN}Verify that{Style.RESET_ALL} {method}")
            else:
                assess_docs = [doc.split(': ', 1)[1] for doc in retrieved_docs if f"Assessment, {control_id}" in doc]
                response.append(f"{Fore.CYAN}Steps to Verify Compliance:{Style.RESET_ALL}")
                if assess_docs:
                    for i, doc in enumerate(assess_docs, 1):
                        response.append(f"  {i}. {Fore.GREEN}Verify that{Style.RESET_ALL} {doc}")
                else:
                    actionable_steps = extract_actionable_steps(ctrl['description'])
                    for i, step in enumerate(actionable_steps, 1):
                        response.append(f"  {i}. {Fore.GREEN}{step.capitalize()}{Style.RESET_ALL}")
                    if ctrl['parameters']:
                        response.append(f"  {len(actionable_steps) + 1}. {Fore.GREEN}Check parameters:{Style.RESET_ALL} {', '.join(ctrl['parameters'])}")

            response.append("")  # Carriage return before STIG section
            response.append("---")
            stig_found = False
            stig_recs_for_checklist = {}
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type and system_type.lower() not in tech_lower:
                    continue
                matching_controls = [k for k in recs.keys() if k.startswith(control_id)]
                stig_recs_for_checklist[tech] = {k: recs[k] for k in matching_controls}
                for matched_control in matching_controls:
                    response.append(f"{Fore.CYAN}#### STIG Assessment for {tech} ({matched_control}){Style.RESET_ALL}")
                    response.append(f"{Fore.WHITE}These STIG rules ensure {ctrl['title'].lower()} on {tech}.{Style.RESET_ALL}")
                    for rec in recs[matched_control]:
                        severity = rec.get('severity', 'medium').capitalize()
                        color = severity_colors.get(severity, Fore.WHITE)
                        response.append(f"- **Rule {rec['rule_id']}**: {rec['title']}")
                        response.append(f"  - {Fore.GREEN}Action:{Style.RESET_ALL} Verify the fix: {rec['fix']}")
                        response.append(f"  - {color}Severity: {severity}{Style.RESET_ALL}")
                    stig_found = True
            if not stig_found and system_type:
                response.append(f"- No STIG assessment guidance found for {system_type}.")
            if stig_found or assess_docs or actionable_steps:
                if generate_checklist:
                    checklist_file = save_checklist(control_id, assess_docs or actionable_steps, stig_recs_for_checklist)
                    response.append("")  # Carriage return before checklist message
                    response.append(f"{Fore.GREEN}Checklist Generated:{Style.RESET_ALL} A CSV file with these steps and STIG checks is available at `{checklist_file}`.")
                else:
                    response.append("")  # Carriage return before tip
                    response.append(f"{Fore.YELLOW}Tip:{Style.RESET_ALL} Run again and select 'y' to generate a checklist for evidence collection.")

        elif is_implementation_query:
            response.append(f"{Fore.CYAN}#### Implementing {control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            response.append(f"{Fore.WHITE}This control enforces {ctrl['title'].lower()}. Implementing it strengthens system security.{Style.RESET_ALL}")
            response.append("---")
            response.append(f"{Fore.CYAN}NIST Implementation Guidance:{Style.RESET_ALL}")
            response.append(f"  1. {Fore.GREEN}Ensure that{Style.RESET_ALL} {ctrl['description']}")

            response.append("")  # Carriage return before STIG section
            response.append("---")
            stig_found = False
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type and system_type.lower() not in tech_lower:
                    continue
                matching_controls = [k for k in recs.keys() if k.startswith(control_id)]
                for matched_control in matching_controls:
                    response.append(f"{Fore.CYAN}#### STIG Implementation for {tech} ({matched_control}){Style.RESET_ALL}")
                    response.append(f"{Fore.WHITE}These STIG rules implement {ctrl['title'].lower()} on {tech}.{Style.RESET_ALL}")
                    for rec in recs[matched_control]:
                        severity = rec.get('severity', 'medium').capitalize()
                        color = severity_colors.get(severity, Fore.WHITE)
                        response.append(f"- **Rule {rec['rule_id']}**: {rec['title']}")
                        response.append(f"  - {Fore.GREEN}Fix:{Style.RESET_ALL} {rec['fix']}")
                        response.append(f"  - {color}Severity: {severity}{Style.RESET_ALL}")
                    stig_found = True
            if not stig_found and system_type:
                response.append(f"- No STIG implementation guidance found for {system_type}.")

    return "\n".join(response)
