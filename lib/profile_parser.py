import yaml


def parse_cv_yaml(raw_yaml: str) -> dict:
    try:
        data = yaml.safe_load(raw_yaml)
    except Exception:
        return {}

    if not data:
        return {}

    cv = data.get("cv", data)
    sections = cv.get("sections", {})

    profile = {
        "name": cv.get("name", ""),
        "title": "",
        "email": "",
        "phone": "",
        "location": "",
        "github": "",
        "linkedin": "",
        "cvUrl": "",
        "summary": "",
        "skills": [],
        "experience": [],
        "projects": [],
        "education": "",
        "certifications": [],
        "languages": []
    }

    # Contact info from cv.social_networks or cv.contact
    for net in cv.get("social_networks", []):
        ntype = net.get("network", "").lower()
        val = net.get("username", "") or net.get("url", "")
        if ntype == "email":
            profile["email"] = val
        elif ntype == "phone":
            profile["phone"] = val
        elif ntype == "github":
            profile["github"] = val
        elif ntype == "linkedin":
            profile["linkedin"] = val
        elif ntype == "location":
            profile["location"] = val

    if not profile["location"]:
        profile["location"] = cv.get("location", "")

    # Title from first experience or cv.label
    profile["title"] = cv.get("label", "") or cv.get("title", "")

    # Summary
    summary_section = sections.get("summary", [])
    if isinstance(summary_section, list) and summary_section:
        profile["summary"] = summary_section[0] if isinstance(summary_section[0], str) else str(summary_section[0])
    elif isinstance(summary_section, str):
        profile["summary"] = summary_section

    # Skills from tech_stack
    skills = set()
    tech_stack = sections.get("tech_stack", sections.get("technologies", sections.get("skills", [])))
    if isinstance(tech_stack, list):
        for item in tech_stack:
            if isinstance(item, dict):
                details = item.get("details", "") or item.get("items", "")
                if isinstance(details, str):
                    for s in details.split(","):
                        s = s.strip()
                        if s:
                            skills.add(s)
                elif isinstance(details, list):
                    for s in details:
                        if isinstance(s, str):
                            skills.add(s.strip())
            elif isinstance(item, str):
                skills.add(item.strip())
    profile["skills"] = sorted(skills)

    # Experience
    experience = sections.get("experience", [])
    if isinstance(experience, list):
        for exp in experience:
            if isinstance(exp, dict):
                profile["experience"].append({
                    "role": exp.get("position", "") or exp.get("role", "") or exp.get("title", ""),
                    "company": exp.get("company", "") or exp.get("organization", ""),
                    "location": exp.get("location", ""),
                    "startDate": exp.get("start_date", "") or exp.get("startDate", ""),
                    "endDate": exp.get("end_date", "") or exp.get("endDate", "") or "Present",
                    "highlights": exp.get("highlights", []) or exp.get("bullets", [])
                })

    if not profile["title"] and profile["experience"]:
        profile["title"] = profile["experience"][0].get("role", "")

    # Projects
    projects = sections.get("projects", [])
    if isinstance(projects, list):
        for proj in projects:
            if isinstance(proj, dict):
                highlights = proj.get("highlights", []) or proj.get("bullets", [])
                stack = ""
                desc = ""
                for h in highlights:
                    h_str = str(h)
                    if "tech stack" in h_str.lower() or "stack:" in h_str.lower():
                        stack = h_str.split(":", 1)[-1].strip() if ":" in h_str else h_str
                    elif "solution" in h_str.lower():
                        desc = h_str.split(":", 1)[-1].strip() if ":" in h_str else h_str
                    elif not desc:
                        desc = h_str
                profile["projects"].append({
                    "name": proj.get("name", "") or proj.get("title", ""),
                    "stack": stack,
                    "desc": desc,
                    "link": proj.get("url", "") or proj.get("link", "")
                })

    # Education
    education = sections.get("education", [])
    if isinstance(education, list) and education:
        edu = education[0]
        if isinstance(edu, dict):
            degree = edu.get("degree", "") or edu.get("study_type", "")
            area = edu.get("area", "") or edu.get("field", "")
            inst = edu.get("institution", "") or edu.get("school", "")
            start = edu.get("start_date", "") or edu.get("startDate", "")
            end = edu.get("end_date", "") or edu.get("endDate", "")
            start_y = str(start)[:4] if start else ""
            end_y = str(end)[:4] if end else ""
            profile["education"] = f"{degree} {area}, {inst} ({start_y}-{end_y})".strip()

    # Certifications
    certs = sections.get("certifications", sections.get("certificates", []))
    if isinstance(certs, list):
        for c in certs:
            if isinstance(c, dict):
                profile["certifications"].append(c.get("name", "") or c.get("title", ""))
            elif isinstance(c, str):
                profile["certifications"].append(c)

    # Languages
    langs = sections.get("languages", [])
    if isinstance(langs, list):
        for lang in langs:
            if isinstance(lang, dict):
                name = lang.get("language", "") or lang.get("name", "")
                level = lang.get("fluency", "") or lang.get("level", "")
                profile["languages"].append(f"{name} ({level})" if level else name)
            elif isinstance(lang, str):
                profile["languages"].append(lang)

    return profile
