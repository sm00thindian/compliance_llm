# src/response_generator.py
import re
import csv
import os
from datetime import datetime
from colorama import Fore, Style
from .text_processing import extract_actionable_steps

def save_checklist(control_id, steps, stig_recommendations, filename_prefix="checklist"):
    """Save assessment steps and STIG recommendations as a CSV checklist in assessment_checklists/."""
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

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, generate_checklist=False):
    """Generate a user-friendly response to a query about NIST 800-53 controls, STIGs, or assessments."""
    query_lower = query.lower()
    response = []

    severity_colors = {
        'High': Fore.RED,
        'Medium': Fore.YELLOW,
        'Low': Fore.GREEN
    }

    if "list stigs" not in query_lower:
        response.append(f"{Fore.YELLOW}**Answering:** '{query}'{Style.RESET_ALL}")
        response.append(f"Here’s what I found based on NIST 800-53 and available STIGs:\n")

    if "list stigs" in query_lower:
        keyword = query_lower.split("for")[1].strip() if "for" in query_lower else None
        filtered_stigs = [
            stig for stig in available_stigs 
            if not keyword or keyword.lower() in stig['technology'].lower() or keyword.lower() in stig['title'].lower()
        ]
        if not filtered_stigs:
            return f"No STIGs found{' for ' + keyword if keyword else ''}. Please check the `stig_folder` in `config.ini`."
        
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

    control_pattern = re.compile(r'\b([A-Z]{2}-[0-9]{1,2}(?:\s*\([a-zA-Z0-9]+\))?)\b')
    control_ids = [match.replace(' ', '') for match in control_pattern.findall(query.upper())]
    system_match = re.search(r'for\s+([Windows|Linux|Red Hat|Ubuntu|macOS|Cisco].*?)(?:\s|$)', query, re.IGNORECASE)
    system_type = system_match.group(1).strip().rstrip('?') if system_match else None

    if control_ids:
        response.append(f"{Fore.YELLOW}**Controls Covered:** {', '.join(control_ids)}{Style.RESET_ALL}" + (f" for {system_type}" if system_type else ""))
    else:
        response.append(f"{Fore.RED}**No NIST controls detected.**{Style.RESET_ALL} Try including a control ID like 'AU-3'.")
        return "\n\n".join(response)

    is_assessment_query = "assess" in query_lower or "audit" in query_lower
    for control_id in control_ids:
        if control_id not in control_details:
            response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
            response.append(f"- **Status:** Not found in the catalog.")
            continue

        ctrl = control_details[control_id]
        response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
        response.append(f"- **Title:** {ctrl['title']}")
        response.append(f"- **Description:** {ctrl['description']}")

        if is_assessment_query:
            response.append(f"\n{Fore.CYAN}#### How to Assess {control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            if control_id in assessment_procedures:
                response.append(f"- **NIST SP 800-53A Assessment Steps:**")
                response.extend(f"  - {method}" for method in assessment_procedures[control_id])
            else:
                assess_docs = [doc.split(': ', 1)[1] for doc in retrieved_docs if f"Assessment, {control_id}" in doc]
                response.append(f"- **Steps to Verify:**")
                if assess_docs:
                    response.extend(f"  - {doc}" for doc in assess_docs)
                else:
                    actionable_steps = extract_actionable_steps(ctrl['description'])
                    response.extend(f"  - {step}" for step in actionable_steps)
                    if ctrl['parameters']:
                        response.append(f"  - Check parameters: {', '.join(ctrl['parameters'])}")

            stig_found = False
            stig_recs_for_checklist = {}
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type and system_type.lower() not in tech_lower:
                    continue
                matching_controls = [k for k in recs.keys() if k.startswith(control_id)]
                stig_recs_for_checklist[tech] = {k: recs[k] for k in matching_controls}
                for matched_control in matching_controls:
                    response.append(f"\n{Fore.CYAN}#### STIG-Based Assessment for {tech} ({matched_control}){Style.RESET_ALL}")
                    for rec in recs[matched_control]:
                        severity = rec.get('severity', 'medium').capitalize()
                        color = severity_colors.get(severity, Fore.WHITE)
                        response.append(f"- **Rule {rec['rule_id']} - {rec['title']}** ({color}Severity: {severity}{Style.RESET_ALL})")
                        response.append(f"  - {Fore.GREEN}**Check:**{Style.RESET_ALL} Verify the fix is applied: {rec['fix']}")
                    stig_found = True
            if not stig_found and system_type:
                response.append(f"- No STIG assessment guidance found for {system_type}.")
            if (stig_found or assess_docs or actionable_steps) and generate_checklist:
                checklist_file = save_checklist(control_id, assess_docs or actionable_steps, stig_recs_for_checklist)
                response.append(f"\n- **Checklist Generated:** Download at `{checklist_file}` for evidence collection.")
        else:
            response.append(f"- **Parameters:** {', '.join(ctrl['parameters']) if ctrl['parameters'] else 'None specified'}")
            response.append(f"- **Related Controls:** {', '.join(ctrl['related_controls']) if ctrl['related_controls'] else 'None'}")
            if control_id in high_baseline_controls:
                response.append(f"- **Baseline:** Included in the High baseline")

        if "implement" in query_lower:
            response.append(f"\n{Fore.CYAN}### Implementation Guidance for {Fore.YELLOW}{control_id}{Style.RESET_ALL}" + (f" on {system_type}" if system_type else ""))
            guidance = [doc.split(': ', 1)[1] for doc in retrieved_docs if control_id in doc and "Assessment" not in doc]
            response.append(f"{Fore.CYAN}#### NIST Guidance{Style.RESET_ALL}")
            if guidance:
                response.extend(f"- {g}" for g in guidance)
            else:
                response.append("- No specific NIST guidance found.")
            stig_found = False
            for tech, recs in all_stig_recommendations.items():
                tech_lower = tech.lower()
                if system_type and system_type.lower() not in tech_lower:
                    continue
                matching_controls = [k for k in recs.keys() if k.startswith(control_id)]
                for matched_control in matching_controls:
                    response.append(f"{Fore.CYAN}#### STIG Recommendations for {tech} ({matched_control}){Style.RESET_ALL}")
                    for rec in recs[matched_control]:
                        short_title = rec['title'].split(' - ')[0][:50] + "..." if len(rec['title']) > 50 else rec['title']
                        response.append(f"- **{Fore.YELLOW}{short_title}{Style.RESET_ALL}** (Rule {rec['rule_id']})")
                        response.append(f"  - {Fore.GREEN}**Fix:**{Style.RESET_ALL} {rec['fix']}")
                    stig_found = True
            if not stig_found:
                response.append(f"{Fore.CYAN}#### STIG Recommendations{Style.RESET_ALL}")
                response.append(f"- No STIGs found for this control{' on ' + system_type if system_type else ''}.")

    if len(response) <= 2:
        response.append(f"{Fore.RED}**No detailed information available.**{Style.RESET_ALL}")
        response.append(f"Try rephrasing your query or visit [nist.gov](https://www.nist.gov).")

    return "\n".join(response)
