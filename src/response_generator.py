import re
import csv
import os
import logging
from datetime import datetime
from colorama import Fore, Style
from .text_processing import extract_actionable_steps
from .parsers import normalize_control_id

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

def generate_response(query, retrieved_docs, control_details, high_baseline_controls, all_stig_recommendations, available_stigs, assessment_procedures, cci_to_nist, generate_checklist=False):
    query_lower = query.lower()
    response = []

    # CCI-specific query handling
    # 1. Specific CCI lookup (e.g., "What is CCI-000130?")
    cci_match = re.search(r"(cci-\d+)", query_lower)
    if cci_match:
        cci_id = cci_match.group(1).upper()
        nist_control = cci_to_nist.get(cci_id, "Not mapped to NIST 800-53 Rev 5")
        normalized_control = normalize_control_id(nist_control)
        response.append(f"{Fore.CYAN}CCI Lookup:{Style.RESET_ALL}")
        response.append(f"- {cci_id} maps to NIST {normalized_control}")
        if normalized_control in control_details:
            ctrl = control_details[normalized_control]
            response.append(f"- **Title:** {ctrl['title']}")
            response.append(f"- **Description:** {ctrl['description']}")
        return "\n".join(response)

    # 2. Reverse lookup (e.g., "List CCI mappings for AU-3")
    reverse_match = re.search(r"(?:list|show)?\s*cci\s*mappings\s*for\s*(\w{2}-\d+(?:\s*[a-z])?(?:\([a-z0-9]+\))?)", query_lower)
    if reverse_match:
        control_id = normalize_control_id(reverse_match.group(1).upper())
        matching_ccis = [cci for cci, nist in cci_to_nist.items() if normalize_control_id(nist) == control_id]
        response.append(f"{Fore.CYAN}CCI Mappings for {control_id}:{Style.RESET_ALL}")
        if matching_ccis:
            for cci in matching_ccis:
                response.append(f"- {cci} -> {control_id}")
            if control_id in control_details:
                ctrl = control_details[control_id]
                response.append(f"\n- **Title:** {ctrl['title']}")
                response.append(f"- **Description:** {ctrl['description']}")
        else:
            response.append(f"- No CCI mappings found for {control_id}.")
        return "\n".join(response)

    # 3. Summary of all mappings (e.g., "Show CCI mappings")
    if "show cci mappings" in query_lower and not reverse_match:
        response.append(f"{Fore.CYAN}CCI-to-NIST Mappings Summary:{Style.RESET_ALL}")
        response.append(f"- Total mappings: {len(cci_to_nist)}")
        response.append("- Sample mappings (first 5):")
        for cci, nist in list(cci_to_nist.items())[:5]:
            response.append(f"  - {cci} -> {nist}")
        if len(cci_to_nist) > 5:
            response.append(f"- ...and {len(cci_to_nist) - 5} more.")
        response.append(f"{Fore.YELLOW}Note:{Style.RESET_ALL} Subparts (e.g., 'A', '1 (A)') refer to specific NIST 800-53 requirements or enhancements.")
        return "\n".join(response)

    # Control summary logic (e.g., "What is AC-2?")
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

    # STIG listing logic
    if "list stigs" in query_lower:
        keyword = query_lower.split("for")[1].strip() if "for" in query_lower else None
        filtered_stigs = [
            stig for stig in available_stigs 
            if not keyword or keyword.lower() in stig['technology'].lower() or keyword.lower() in stig['title'].lower()
        ]
        if not filtered_stigs:
            return f"No STIGs found{' for ' + keyword if keyword else ''}. Please check the `stig_folder` in `config.ini`."
        
        response.append(f"{Fore.CYAN}### Available STIGs{Style.RESET_ALL}")
        response.append(f"Here’s a list of {len(filtered_stigs)} STIG(s) loaded in the system:\n")
        for i, stig in enumerate(filtered_stigs, 1):
            tech = stig['technology']
            version = stig['version']
            title = stig['title']
            file = stig['file']
            response.append(f"{Fore.YELLOW}{i}. {tech} (Version {version}){Style.RESET_ALL}")
            response.append(f"   - Title: {title}")
            response.append(f"   - File: {file}")
            response.append("")  # Blank line for spacing
        response.append(f"{Fore.GREEN}Tip:{Style.RESET_ALL} Use 'assess <control>' or 'implement <control>' to see STIG recommendations.")
        return "\n".join(response)

    # Control-specific logic for assessment or implementation
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

    # Extract technology hint from query (e.g., "on VMware")
    tech_hint = None
    tech_match = re.search(r'on\s+([a-zA-Z0-9][a-zA-Z0-9\s\-]*[a-zA-Z0-9])\b', query_lower, re.IGNORECASE)
    if tech_match:
        tech_hint = tech_match.group(1).strip().lower()
        logging.debug(f"Detected tech hint: {tech_hint}")

    # Map technologies to STIGs and find applicable ones
    tech_to_stig = {get_technology_name(stig).lower(): stig for stig in available_stigs}  # Normalize to lowercase for matching
    all_techs = sorted(set(tech_to_stig.keys()))  # All available technologies
    applicable_techs = []
    for tech, stig in tech_to_stig.items():
        for control_id in control_ids:
            if control_id in all_stig_recommendations.get(stig['technology'], {}):
                applicable_techs.append(tech)
                logging.debug(f"Found STIG match: {tech} for control {control_id}")
                break

    unique_techs = sorted(set(applicable_techs))
    logging.debug(f"Applicable technologies before filtering: {unique_techs}")

    # Filter technologies based on hint
    if tech_hint:
        matching_techs = [t for t in all_techs if tech_hint.lower() in t.lower()]  # Check all techs, not just applicable
        if matching_techs:
            unique_techs = sorted(set(matching_techs) & set(applicable_techs)) or matching_techs  # Prefer applicable, fallback to hint
            logging.debug(f"Filtered to technologies matching '{tech_hint}': {unique_techs}")
        else:
            logging.debug(f"No match for '{tech_hint}', using applicable techs")

    if not unique_techs and applicable_techs:
        unique_techs = applicable_techs  # Fallback to applicable if hint filtering fails
        logging.debug(f"Fallback to applicable techs: {unique_techs}")

    if selected_idx is None and len(unique_techs) > 1:
        response.append(f"{Fore.CYAN}### Select a Technology{Style.RESET_ALL}")
        response.append(f"Multiple technologies support {', '.join(control_ids)}. Please choose one:\n")
        for i, tech in enumerate(unique_techs, 1):
            stig = tech_to_stig[tech]
            response.append(f"{Fore.YELLOW}{i}. {stig['technology']} (Version {stig['version']}){Style.RESET_ALL}")
            response.append(f"   - Title: {stig['title']}")
        response.append(f"\n{Fore.GREEN}Next Step:{Style.RESET_ALL} Enter a number (1-{len(unique_techs)}, or 0 for all) to proceed.")
        return "\n".join(response) + "\nCLARIFICATION_NEEDED"  # Signal to main() for prompt

    # Determine selected technologies
    if selected_idx == 0:
        selected_techs = [tech_to_stig[t]['technology'] for t in unique_techs]
    elif selected_idx is not None and 1 <= selected_idx <= len(unique_techs):
        selected_techs = [tech_to_stig[unique_techs[selected_idx - 1]]['technology']]
    elif len(unique_techs) == 1:
        selected_techs = [tech_to_stig[unique_techs[0]]['technology']]  # Auto-select if only one match
    elif not unique_techs:
        selected_techs = []  # No applicable STIGs
    else:
        return "Invalid technology selection."

    logging.debug(f"Selected technologies: {selected_techs}")

    # Build response
    action = "Assessing" if is_assessment_query else "Implementing"
    response.append(f"{Fore.CYAN}### {action} {', '.join(control_ids)}{Style.RESET_ALL}")
    response.append(f"Based on NIST 800-53 Rev 5 and available STIGs:\n")

    for control_id in control_ids:
        if control_id not in control_details:
            response.append(f"{Fore.YELLOW}1. {control_id}{Style.RESET_ALL}")
            response.append(f"   - Status: Not found in NIST 800-53 Rev 5 catalog.")
            response.append("")
            continue

        ctrl = control_details[control_id]
        response.append(f"{Fore.YELLOW}1. {control_id} - {ctrl['title']}{Style.RESET_ALL}")
        response.append(f"   - Purpose: {ctrl['description'].split('.')[0].lower()}.")
        response.append("")

        if is_assessment_query:
            response.append(f"{Fore.CYAN}   Steps to Assess:{Style.RESET_ALL}")
            if control_id in assessment_procedures:
                for i, method in enumerate(assessment_procedures[control_id], 1):
                    response.append(f"     {i}. {method}")
            else:
                assess_docs = [doc.split(': ', 1)[1] for doc in retrieved_docs if f"Assessment, {control_id}" in doc]
                steps = assess_docs if assess_docs else extract_actionable_steps(ctrl['description'])
                for i, step in enumerate(steps, 1):
                    response.append(f"     {i}. {step}")
                if ctrl.get('parameters'):
                    response.append(f"     {len(steps) + 1}. Confirm parameters: {', '.join(ctrl['parameters'])}")
            response.append("")

            if selected_techs:
                for tech in selected_techs:
                    recs = all_stig_recommendations.get(tech, {}).get(control_id, [])
                    if recs:
                        response.append(f"{Fore.CYAN}   STIG Checks for {tech}:{Style.RESET_ALL}")
                        for i, rec in enumerate(recs, 1):
                            severity = rec.get('severity', 'medium').capitalize()
                            color = severity_colors.get(severity, Fore.WHITE)
                            response.append(f"     {i}. {rec['title']} (Rule {rec['rule_id']})")
                            response.append(f"        - {Fore.GREEN}Verify:{Style.RESET_ALL} {rec['fix']}")
                            response.append(f"        - {color}Severity: {severity}{Style.RESET_ALL}")
                        response.append("")
                    else:
                        response.append(f"{Fore.CYAN}   STIG Checks for {tech}:{Style.RESET_ALL}")
                        response.append(f"     1. No specific STIG checks available.")
                        response.append("")

            if generate_checklist:
                steps = assess_docs if 'assess_docs' in locals() else extract_actionable_steps(ctrl['description'])
                stig_recs_for_checklist = {tech: {control_id: all_stig_recommendations.get(tech, {}).get(control_id, [])} for tech in selected_techs if all_stig_recommendations.get(tech, {}).get(control_id)}
                if steps or stig_recs_for_checklist:
                    checklist_file = save_checklist(control_id, steps, stig_recs_for_checklist)
                    response.append(f"   - {Fore.GREEN}Checklist Saved:{Style.RESET_ALL} See `{checklist_file}`")
                    response.append("")

        elif is_implement_query:
            response.append(f"{Fore.CYAN}   How to Implement:{Style.RESET_ALL}")
            guidance = [doc.split(': ', 1)[1] for doc in retrieved_docs if control_id in doc and "Assessment" not in doc]
            if guidance:
                for i, step in enumerate(guidance, 1):
                    response.append(f"     {i}. {step}")
            else:
                response.append(f"     1. Follow the control description to enforce this requirement.")
            response.append("")

            if selected_techs:
                for tech in selected_techs:
                    recs = all_stig_recommendations.get(tech, {}).get(control_id, [])
                    if recs:
                        response.append(f"{Fore.CYAN}   STIG Guidance for {tech}:{Style.RESET_ALL}")
                        for i, rec in enumerate(recs, 1):
                            short_title = rec['title'][:50] + "..." if len(rec['title']) > 50 else rec['title']
                            response.append(f"     {i}. {short_title} (Rule {rec['rule_id']})")
                            response.append(f"        - {Fore.GREEN}Apply:{Style.RESET_ALL} {rec['fix']}")
                        response.append("")
                    else:
                        response.append(f"{Fore.CYAN}   STIG Guidance for {tech}:{Style.RESET_ALL}")
                        response.append(f"     1. No specific STIG guidance available.")
                        response.append("")

    if len(response) <= 2:  # Only header present
        response.append(f"{Fore.RED}No specific information found for this query.{Style.RESET_ALL}")

    return "\n".join(response)
