import re
import csv
import os
import logging
from datetime import datetime
from colorama import Fore, Style
from .text_processing import extract_actionable_steps

family_purposes = {
    "AC": "manage access to information systems and resources",
    "AT": "provide security awareness and training",
    "AU": "monitor and review system activities for security and compliance",
    "CA": "assess and authorize information systems",
    "CM": "manage system configurations",
    "CP": "ensure contingency planning for system resilience",
    "IA": "identify and authenticate users and systems",
    "IR": "respond to security incidents",
    "MA": "maintain information systems",
    "MP": "protect media containing sensitive information",
    "PE": "manage physical access to facilities and systems",
    "PL": "plan for security and privacy in system development",
    "PM": "manage security and privacy programs",
    "PS": "manage personnel security",
    "PT": "manage personally identifiable information (PII) processing",
    "RA": "assess and manage risks",
    "SA": "acquire and manage system development and maintenance",
    "SC": "implement system and communications protection",
    "SI": "ensure system and information integrity",
    "SR": "manage supply chain risks",
}

severity_colors = {
    'High': Fore.RED,
    'Medium': Fore.YELLOW,
    'Low': Fore.GREEN
}

def save_checklist(control_id, steps, stig_recommendations, filename_prefix="checklist"):
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

def get_technology_name(stig):
    title = stig.get('title', 'Untitled')
    tech = stig.get('technology', title)
    if "STIG" in title and title != "Untitled STIG" and len(title.split()) > 2:
        return " ".join(word for word in title.split() if "STIG" not in word and "V" not in word and "R" not in word[:2])
    return tech

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, generate_checklist=False):
    query_lower = query.lower()
    response = []

    control_summary_match = re.search(r"what is\s+(\w{2}-\d+(?:\(\d+\))?)\s*\?", query_lower)
    if control_summary_match:
        control_id = control_summary_match.group(1).upper()
        if control_id in control_details:
            ctrl = control_details[control_id]
            description = ctrl['description']
            if "[withdrawn:" in description.lower():
                match = re.search(r"Incorporated into (\w{2}-\d+(?:\(\d+\))?)", description, re.IGNORECASE)
                if match:
                    incorporated_into = match.group(1).upper()
                    response.append(f"{control_id} has been withdrawn and incorporated into {incorporated_into}.")
                else:
                    response.append(f"{control_id} has been withdrawn.")
            else:
                first_sentence = description.split('.')[0]
                family = control_id.split('-')[0]
                purpose = family_purposes.get(family, "address specific security and privacy requirements")
                summary = (
                    f"{control_id} is the control for \"{ctrl['title']}\" in the NIST 800-53 Revision 5 catalog. "
                    f"This control requires organizations to {first_sentence.lower()}. "
                    f"Essentially, this control helps organizations {purpose}."
                )
                response.append(summary)
                response.append(f"\n{Fore.CYAN}#### What Does {control_id} Entail?{Style.RESET_ALL}\n{description}")
                if ctrl.get('parameters'):
                    response.append(f"\n{Fore.YELLOW}**Parameters:**{Style.RESET_ALL} {', '.join(ctrl['parameters'])}")
                if ctrl.get('related_controls'):
                    response.append(f"\n{Fore.YELLOW}**Related Controls:**{Style.RESET_ALL} {', '.join(ctrl['related_controls'])}")
        else:
            response.append(f"Control {control_id} not found in the NIST 800-53 Revision 5 catalog.")
        return "\n".join(response)

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
    system_match = re.search(r'with technology index\s*(\d+)', query_lower)
    selected_idx = int(system_match.group(1)) if system_match else None

    if not control_ids:
        response.append(f"{Fore.RED}**No NIST controls detected.**{Style.RESET_ALL} Try including a control ID like 'AU-3'.")
        return "\n\n".join(response)

    is_assessment_query = "assess" in query_lower or "audit" in query_lower
    is_implement_query = "implement" in query_lower

    if not (is_assessment_query or is_implement_query):
        response.append(f"{Fore.YELLOW}**Answering:** '{query}'{Style.RESET_ALL}")
        response.append(f"Here’s what I found based on NIST 800-53 and available STIGs:\n")
        response.append("Relevant info: " + "\n".join(retrieved_docs[:5]))
        return "\n".join(response)

    applicable_techs = []
    tech_to_stig = {get_technology_name(stig): stig for stig in available_stigs}
    for stig in available_stigs:
        tech = get_technology_name(stig)
        for control_id in control_ids:
            if control_id in all_stig_recommendations.get(tech, {}):
                applicable_techs.append(tech)
                logging.debug(f"Found STIG match: {tech} for control {control_id}")
                break
        else:
            logging.debug(f"No STIG match for {tech} with controls {control_ids}")

    unique_techs = sorted(set(applicable_techs))
    logging.debug(f"Applicable technologies: {unique_techs}")

    if selected_idx is None:
        if not unique_techs and not available_stigs:
            response.append(f"No STIGs loaded. Please check the `stig_folder` in `config.ini`.")
        elif not unique_techs:
            response.append("No direct STIG recommendations found, but you can select a technology for general guidance:")
        else:
            response.append("Multiple STIG technologies available:")
        for i, tech in enumerate(tech_to_stig.keys(), 1):
            response.append(f"  {i}. {tech}")
        response.append(f"Select a technology (1-{len(tech_to_stig)}, or 0 for all): ")
        return "\n".join(response)

    if selected_idx == 0:
        selected_techs = list(tech_to_stig.keys())
    elif 1 <= selected_idx <= len(tech_to_stig):
        selected_techs = [list(tech_to_stig.keys())[selected_idx - 1]]
    else:
        return "Invalid selection."

    logging.debug(f"Selected technologies: {selected_techs}")

    response.append(f"{Fore.YELLOW}**{'Assessing' if is_assessment_query else 'Implementing'} {', '.join(control_ids)}:**{Style.RESET_ALL}")
    has_content = False
    
    for control_id in control_ids:
        if control_id not in control_details:
            response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
            response.append(f"- **Status:** Not found in the catalog.")
            continue

        ctrl = control_details[control_id]
        response.append(f"{Fore.CYAN}### Control: {Fore.YELLOW}{control_id}{Style.RESET_ALL}")
        response.append(f"- **Title:** {ctrl['title']}")
        response.append(f"- **Description:** {ctrl['description']}")
        has_content = True

        if is_assessment_query:
            response.append(f"\n{Fore.CYAN}#### How to Assess {control_id}{Style.RESET_ALL}")
            if control_id in assessment_procedures:
                response.append(f"- **NIST SP 800-53A Assessment Steps:**")
                response.extend(f"  - {method}" for method in assessment_procedures[control_id])
                has_content = True
            else:
                assess_docs = [doc.split(': ', 1)[1] for doc in retrieved_docs if f"Assessment, {control_id}" in doc]
                response.append(f"- **Steps to Verify:**")
                if assess_docs:
                    response.extend(f"  - {doc}" for doc in assess_docs)
                    has_content = True
                else:
                    actionable_steps = extract_actionable_steps(ctrl['description'])
                    response.extend(f"  - {step}" for step in actionable_steps)
                    if ctrl['parameters']:
                        response.append(f"  - Check parameters: {', '.join(ctrl['parameters'])}")
                    has_content = True

            stig_recs_for_checklist = {}
            for tech in selected_techs:
                recs = all_stig_recommendations.get(tech, {}).get(control_id, [])
                if recs:
                    stig_recs_for_checklist[tech] = {control_id: recs}
                    response.append(f"\n{Fore.CYAN}#### STIG-Based Assessment for {tech}{Style.RESET_ALL}")
                    for rec in recs:
                        severity = rec.get('severity', 'medium').capitalize()
                        color = severity_colors.get(severity, Fore.WHITE)
                        response.append(f"- **Rule {rec['rule_id']} - {rec['title']}** ({color}Severity: {severity}{Style.RESET_ALL})")
                        response.append(f"  - {Fore.GREEN}**Check:**{Style.RESET_ALL} Verify the fix is applied: {rec['fix']}")
                    has_content = True
                else:
                    response.append(f"\n{Fore.CYAN}#### STIG-Based Assessment for {tech}{Style.RESET_ALL}")
                    response.append(f"- No specific STIG recommendations found for {control_id}.")

            if generate_checklist and (assess_docs or actionable_steps or stig_recs_for_checklist):
                checklist_file = save_checklist(control_id, assess_docs or actionable_steps, stig_recs_for_checklist)
                response.append(f"\n- **Checklist Generated:** Download at `{checklist_file}` for evidence collection.")

        elif is_implement_query:
            response.append(f"\n{Fore.CYAN}#### Implementation Guidance for {control_id}{Style.RESET_ALL}")
            guidance = [doc.split(': ', 1)[1] for doc in retrieved_docs if control_id in doc and "Assessment" not in doc]
            response.append(f"{Fore.CYAN}##### NIST Guidance{Style.RESET_ALL}")
            if guidance:
                response.extend(f"- {g}" for g in guidance)
                has_content = True
            else:
                response.append("- No specific NIST guidance found.")
            for tech in selected_techs:
                recs = all_stig_recommendations.get(tech, {}).get(control_id, [])
                if recs:
                    response.append(f"{Fore.CYAN}##### STIG Recommendations for {tech}{Style.RESET_ALL}")
                    for rec in recs:
                        short_title = rec['title'].split(' - ')[0][:50] + "..." if len(rec['title']) > 50 else rec['title']
                        response.append(f"- **{Fore.YELLOW}{short_title}{Style.RESET_ALL}** (Rule {rec['rule_id']})")
                        response.append(f"  - {Fore.GREEN}**Fix:**{Style.RESET_ALL} {rec['fix']}")
                    has_content = True
                else:
                    response.append(f"{Fore.CYAN}##### STIG Recommendations for {tech}{Style.RESET_ALL}")
                    response.append(f"- No specific STIG recommendations found for {control_id}.")

    if not has_content:
        response.append(f"{Fore.RED}No specific information found for this query.{Style.RESET_ALL}")

    return "\n".join(response)
