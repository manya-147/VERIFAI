"""Resume analysis for the Resume Match page (no external AI service needed).

* extract_pdf_text()  – text from an uploaded PDF (needs `pip install pypdf`)
* analyze_resume()    – text -> profile: skills / tech stack, experience, level, target roles, education, location
* build_queries()     – profile -> web-search queries for TinyFish
* score_listing()     – how well a scraped job/internship fits the profile
"""

from __future__ import annotations

import io
import re
from datetime import date

# ───────── PDF ─────────


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("PDF support needs pypdf. Run:  pip install pypdf   (or: uv add pypdf)") from error
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f"Could not read that PDF ({error.__class__.__name__}). Try pasting the text instead.") from error
    if len(text.strip()) < 40:
        raise RuntimeError("No readable text in that PDF (it may be a scanned image). Paste the text instead.")
    return text


# ───────── Skills / tech stack ─────────
# canonical name -> (category, aliases matched as whole words, case-insensitive)
_SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {}


def _add(category: str, *names: str | tuple[str, ...]) -> None:
    for entry in names:
        canonical, *aliases = (entry,) if isinstance(entry, str) else entry
        _SKILLS[canonical] = (category, tuple([canonical, *aliases]))


_add("Languages", "Python", "Java", ("JavaScript", "JS", "ECMAScript"), ("TypeScript", "TS"), ("C++", "cpp"), ("C#", "csharp"),
     "Go", ("Golang",), "Rust", "Kotlin", "Swift", "Ruby", "PHP", "Scala", "R", "MATLAB", "Dart", "Bash", "SQL", "Solidity",
     "Perl", "Haskell", "Lua")
_add("Frontend", "React", ("Next.js", "NextJS"), ("Angular", "AngularJS"), ("Vue", "Vue.js", "VueJS"), "Svelte", "HTML", "CSS",
     ("Tailwind", "TailwindCSS"), "Redux", "Bootstrap", "jQuery", "Flutter", ("React Native", "ReactNative"), "Figma")
_add("Backend", ("Node.js", "NodeJS", "Node"), ("Express", "Express.js"), "Django", "Flask", "FastAPI", ("Spring Boot", "SpringBoot", "Spring"),
     ".NET", "Laravel", "GraphQL", ("REST", "RESTful", "REST API", "REST APIs"), "gRPC", "Microservices", "Kafka", "RabbitMQ")
_add("Data & ML", ("Machine Learning", "ML"), ("Deep Learning", "DL"), "NLP", ("Computer Vision", "CV"), "TensorFlow", "PyTorch",
     ("Scikit-learn", "sklearn", "scikit learn"), "Keras", "Pandas", "NumPy", "OpenCV", "Hugging Face", ("LLM", "LLMs"),
     ("LangChain",), ("Generative AI", "GenAI"), "RAG", "XGBoost", "Spark", "Hadoop", "Airflow", "dbt", "Tableau", ("Power BI", "PowerBI"),
     ("Data Analysis", "Data Analytics"), ("Data Visualization",), "Excel", "Statistics", "A/B Testing")
_add("Databases", "MySQL", ("PostgreSQL", "Postgres"), "MongoDB", "Redis", "SQLite", "Firebase", "Elasticsearch", "DynamoDB",
     "Cassandra", "Supabase", "Oracle", "Snowflake", "BigQuery")
_add("Cloud & DevOps", ("AWS", "Amazon Web Services"), ("GCP", "Google Cloud"), "Azure", "Docker", ("Kubernetes", "K8s"), "Terraform",
     ("CI/CD", "CICD"), "Jenkins", ("GitHub Actions",), "Linux", "Nginx", "Ansible", "Prometheus", "Grafana", "Serverless")
_add("Tools & Practices", "Git", "GitHub", "GitLab", "Jira", "Postman", "Agile", "Scrum", ("Data Structures", "DSA", "Algorithms"),
     ("OOP", "Object Oriented Programming"), ("System Design",), ("Unit Testing", "Jest", "Pytest", "JUnit"), "Selenium",
     "Android", "iOS", "Unity", "Blockchain", ("Cybersecurity", "Cyber Security", "Penetration Testing"), "Embedded", "IoT", "Arduino")

_SPECIAL = {"C++": r"(?<![\w+])c\+\+(?![\w+])", "C#": r"(?<![\w#])c#(?![\w#])", ".NET": r"(?<![\w.])\.net\b",
            "Node.js": r"\bnode(?:\.?js)?\b", "Next.js": r"\bnext(?:\.?js)\b", "Go": r"\b(?:golang|go)\b(?!\s+(?:to|for|with|through))",
            "R": r"(?<![\w.+#])R(?![\w.+#/&])", "CI/CD": r"\bci\s*/\s*cd\b"}
_PATTERNS: dict[str, re.Pattern] = {}
for _name, (_cat, _aliases) in _SKILLS.items():
    if _name in _SPECIAL:
        _PATTERNS[_name] = re.compile(_SPECIAL[_name], 0 if _name == "R" else re.I)
    else:
        parts = [r"(?<![\w.#+])" + re.escape(a).replace(r"\ ", r"[\s-]*") + r"(?![\w#+]|\.\w)" for a in _aliases]
        _PATTERNS[_name] = re.compile("|".join(parts), re.I)


def find_skills(text: str) -> list[str]:
    """Skills mentioned in text, most-mentioned first."""
    hits = []
    for name, pattern in _PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            hits.append((count, -text.lower().find(name.lower()) if name.lower() in text.lower() else 0, name))
    hits.sort(reverse=True)
    return [name for _, _, name in hits]


def skill_category(name: str) -> str:
    return _SKILLS.get(name, ("Other",))[0]


# ───────── Sections ─────────
_HEADINGS = {
    "experience": r"(?:work\s+|professional\s+|relevant\s+)?experience|employment(?:\s+history)?|internships?|work\s+history",
    "education": r"education|academics?|academic\s+(?:background|qualifications?)|qualifications?",
    "projects": r"(?:personal\s+|academic\s+|key\s+)?projects?",
    "skills": r"(?:technical\s+|key\s+|core\s+)?skills?(?:\s*(?:&|and)\s*\w+)?|tech(?:nical)?\s+stack|technologies",
    "other": r"summary|objective|profile|about(?:\s+me)?|achievements?|awards?|certifications?|publications?|"
             r"positions?\s+of\s+responsibility|extra[-\s]?curriculars?|activities|interests|languages|references",
}
_HEAD_RE = {k: re.compile(rf"^\s*(?:{v})\s*:?\s*$", re.I) for k, v in _HEADINGS.items()}


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.splitlines():
        stripped = line.strip().strip("•-–—|*#_ ")
        key = next((k for k, rx in _HEAD_RE.items() if len(stripped) <= 40 and rx.match(stripped)), None)
        if key:
            current = key if key != "other" else "other"
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


# ───────── Experience ─────────
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_RANGE = re.compile(
    rf"(?:{_MON}[\s,'’]*)?((?:19|20)\d\d)\s*(?:-|–|—|to|until)\s*(?:(present|current|now|ongoing|till\s+date|date)|(?:{_MON}[\s,'’]*)?((?:19|20)\d\d))",
    re.I)


def _month_index(year: int, month: str | None) -> int:
    return year * 12 + (_MONTHS[month[:3].lower()] - 1 if month else 0)


def estimate_experience(text: str, today: date | None = None) -> float:
    """Years of work experience: stated ("3+ years") or the union of dated ranges in the experience section."""
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    spans = []
    for m in _RANGE.finditer(text):
        m1, y1, current, m2, y2 = m.group(1), int(m.group(2)), m.group(3), m.group(4), m.group(5)
        start = _month_index(y1, m1)
        end = now if current else _month_index(int(y2), m2) + (1 if m2 else 12)
        if not current and not m2:
            end = _month_index(int(y2), None) + 6   # a bare year such as "2021 – 2023": count to mid-year
        if start < end <= now + 1 and end - start <= 12 * 40:
            spans.append((start, end))
    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    from_dates = sum(e - s for s, e in merged) / 12

    stated = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:\w+\s+){0,3}?experience", text, re.I)]
    best = max([from_dates, *(stated or [0])])
    return round(min(best, 40), 1)


def level_for(years: float, is_student: bool) -> str:
    if is_student and years < 1.5:
        return "intern"
    if years < 1:
        return "entry"
    if years < 3:
        return "junior"
    if years < 6:
        return "mid"
    return "senior"


# ───────── Roles ─────────
# role -> (title regex, skill hints)
_ROLES: dict[str, tuple[str, set[str]]] = {
    "Software Engineer": (r"software\s+(?:engineer|developer)|sde|swe", {"Data Structures", "System Design", "Java", "Python", "C++", "Git"}),
    "Frontend Developer": (r"front[\s-]?end|ui\s+developer|web\s+developer", {"React", "Next.js", "Angular", "Vue", "HTML", "CSS", "TypeScript", "JavaScript", "Tailwind"}),
    "Backend Developer": (r"back[\s-]?end|api\s+developer", {"Node.js", "Django", "Flask", "FastAPI", "Spring Boot", "Express", "PostgreSQL", "MongoDB", "REST", "Microservices"}),
    "Full Stack Developer": (r"full[\s-]?stack|mern|mean\s+stack", {"React", "Node.js", "MongoDB", "Express", "JavaScript", "TypeScript", "PostgreSQL"}),
    "Data Scientist": (r"data\s+scientist", {"Machine Learning", "Python", "Pandas", "NumPy", "Scikit-learn", "Statistics", "Deep Learning"}),
    "Machine Learning Engineer": (r"(?:machine\s+learning|ml|ai)\s+(?:engineer|developer|intern)|deep\s+learning\s+engineer", {"Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "NLP", "Computer Vision", "LLM", "Keras"}),
    "AI Engineer": (r"ai\s+(?:engineer|developer)|generative\s+ai|llm\s+engineer", {"LLM", "LangChain", "Generative AI", "RAG", "Hugging Face", "NLP"}),
    "Data Analyst": (r"data\s+analyst|business\s+analyst|bi\s+(?:analyst|developer)", {"SQL", "Excel", "Tableau", "Power BI", "Data Analysis", "Pandas", "Data Visualization"}),
    "Data Engineer": (r"data\s+engineer", {"Spark", "Hadoop", "Airflow", "Kafka", "SQL", "Snowflake", "BigQuery", "dbt"}),
    "DevOps Engineer": (r"dev[\s-]?ops|site\s+reliability|sre|cloud\s+engineer", {"Docker", "Kubernetes", "AWS", "Terraform", "CI/CD", "Jenkins", "Linux", "Azure", "GCP"}),
    "Android Developer": (r"android\s+developer", {"Android", "Kotlin", "Java", "Firebase"}),
    "Mobile App Developer": (r"(?:mobile|app|ios|flutter)\s+developer", {"Flutter", "React Native", "Swift", "Dart", "iOS", "Android", "Kotlin"}),
    "Cybersecurity Analyst": (r"security\s+(?:analyst|engineer)|cyber", {"Cybersecurity", "Linux", "Python", "Bash"}),
    "QA / Test Engineer": (r"qa\b|test\s+engineer|sdet|quality\s+assurance", {"Selenium", "Unit Testing", "Postman", "Jira", "Java", "Python"}),
    "UI/UX Designer": (r"ui\s*/?\s*ux|product\s+designer|ux\s+designer", {"Figma"}),
}


def infer_roles(text: str, skills: list[str], experience_text: str = "") -> list[str]:
    skill_set = set(skills)
    scored = []
    for role, (title_rx, hints) in _ROLES.items():
        title_hits = len(re.findall(title_rx, text, re.I)) + 2 * len(re.findall(title_rx, experience_text, re.I))
        skill_hits = len(skill_set & hints)
        if title_hits or skill_hits >= 2:
            scored.append((title_hits * 3 + skill_hits, role))
    scored.sort(reverse=True)
    roles = [r for _, r in scored[:3]]
    return roles or (["Software Engineer"] if skills else [])


# ───────── Education / location / name ─────────
_DEGREE = re.compile(
    r"(b\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc|b\.?\s?c\.?a|bachelor[^\n,;]{0,40}|m\.?\s?tech|m\.?\s?sc|m\.?\s?c\.?a|master[^\n,;]{0,40}|mba|ph\.?\s?d|b\.?\s?com|diploma[^\n,;]{0,30})",
    re.I)
_CITIES = ["Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Delhi", "New Delhi", "Noida", "Gurgaon", "Gurugram", "Chennai", "Kolkata",
           "Ahmedabad", "Jaipur", "Indore", "Chandigarh", "Kochi", "Coimbatore", "Remote", "London", "Berlin", "Singapore", "Dubai",
           "San Francisco", "New York", "Seattle", "Austin", "Toronto", "Sydney", "Bhopal", "Lucknow", "Nagpur", "Surat"]


def parse_education(text: str, today: date | None = None) -> tuple[str, bool]:
    """(degree line, currently a student?)"""
    today = today or date.today()
    match = _DEGREE.search(text)
    line = ""
    if match:
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        line = re.sub(r"\s+", " ", text[start: end if end != -1 else None]).strip()[:140]
    years = [int(y) for y in re.findall(r"\b(20\d\d)\b", text)]
    grad = [int(y) for y in re.findall(r"(?:expected|graduat\w+|batch|class\s+of|until|–|-|to)\s*(?:of\s*)?(20\d\d)\b", text, re.I)]
    future = [y for y in (grad or years) if y >= today.year]
    in_progress = bool(re.search(r"\b(pursuing|currently|expected|present)\b", text, re.I))
    return line, bool(future) or (in_progress and bool(match))


def detect_location(text: str) -> str:
    head = "\n".join(text.splitlines()[:15])
    for city in _CITIES:
        if re.search(rf"\b{re.escape(city)}\b", head, re.I):
            return {"Bangalore": "Bengaluru", "Gurgaon": "Gurugram"}.get(city, city)
    return ""


def detect_name(text: str) -> str:
    for line in text.splitlines()[:6]:
        clean = line.strip()
        if 2 <= len(clean) <= 40 and not re.search(r"[@\d/|:]|resume|curriculum|vitae", clean, re.I) and len(clean.split()) <= 4:
            return clean.title() if clean.isupper() else clean
    return ""


# ───────── Main entry ─────────


def analyze_resume(text: str) -> dict:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    sections = split_sections(text)
    exp_text = "\n".join(sections.get(k, "") for k in ("experience",))
    # skills listed in a Skills section count first, then the rest of the resume
    skills = find_skills(sections.get("skills", "") + "\n" + text)
    years = estimate_experience(exp_text or "")
    if not exp_text:
        years = min(estimate_experience(text), 40) if re.search(r"\b(?:experience|worked|employed)\b", text, re.I) else 0.0
    education, student = parse_education(sections.get("education", "") or text)
    level = level_for(years, student)
    roles = infer_roles(text, skills, exp_text)
    return {
        "name": detect_name(text),
        "skills": skills[:30],
        "skill_groups": {c: [s for s in skills[:30] if skill_category(s) == c] for c in dict.fromkeys(skill_category(s) for s in skills[:30])},
        "years": years,
        "level": level,
        "roles": roles,
        "education": education,
        "student": student,
        "location": detect_location(text),
        "job_type": "internship" if level == "intern" else "job",
        "chars": len(text),
    }


# ───────── Search + scoring ─────────


def _top_skills(role: str, skills: list[str], n: int = 3) -> str:
    """Skills of the candidate that matter most for this role first, then their strongest remaining skills."""
    hints = _ROLES.get(role, ("", set()))[1]
    ranked = [s for s in skills if s in hints] + [s for s in skills if s not in hints]
    return " ".join(ranked[:n])


def build_queries(roles: list[str], skills: list[str], level: str, job_type: str, location: str) -> list[str]:
    """Up to 3 web-search queries, one per target role, each with the strongest tech-stack keywords."""
    roles = [r.strip() for r in roles if r.strip()] or ["Software Engineer"]
    where = f" {location}" if location.strip() else ""
    kinds = ["internship", "job"] if job_type == "both" else [job_type if job_type in ("internship", "job") else "job"]
    seniority = {"senior": "senior ", "mid": "", "junior": "junior ", "entry": "entry level ", "intern": ""}.get(level, "")
    queries = []
    for i, role in enumerate(roles[:3]):
        kind = kinds[i % len(kinds)]
        queries.append(f"{seniority if kind == 'job' else ''}{role} {kind} {_top_skills(role, skills)}{where} apply 2026".replace("  ", " ").strip())
    if len(kinds) == 2 and len(roles) == 1:
        queries.append(f"{roles[0]} {kinds[1]} {_top_skills(roles[0], skills)}{where} apply 2026".replace("  ", " "))
    return list(dict.fromkeys(queries))


def resume_goal(roles: list[str], skills: list[str], level: str, years: float, job_type: str, location: str) -> str:
    kind = {"internship": "internships", "job": "jobs", "both": "jobs and internships"}.get(job_type, "jobs")
    # Keep this short and page-local: telling the agent to browse "reached from" the page made runs
    # exceed PAGE_TIMEOUT, so every page was reported as skipped.
    return (
        f"Use only this page (do not browse to other sites or log in) and finish quickly. List up to 5 open {kind} shown on it, "
        f"preferring ones that fit: {', '.join(roles[:3]) or 'software'}; skills: {', '.join(skills[:8]) or 'software'}; "
        f"{level or 'entry'} level{'; ' + location if location else ''}. "
        "For each give title, organization, location, remote (true/false), deadline, apply_link (full URL), category, "
        "required_skills (comma-separated technologies) and experience_required (e.g. '0-2 years'). "
        "Use an empty string for anything unavailable. If the page has no job listings, return an empty list."
    )


def score_listing(item: dict, skills: list[str], roles: list[str], level: str) -> dict:
    """Add match_score (0-100), matched_skills and missing_skills to a listing."""
    mine = set(skills)
    blob_req = f"{item.get('required_skills', '')} {item.get('title', '')}"
    theirs = {s for s in _PATTERNS if _PATTERNS[s].search(blob_req)}
    matched = sorted(mine & theirs)
    missing = sorted(theirs - mine)
    if theirs:
        skill_part = 65 * len(matched) / len(theirs)
    else:
        skill_part = 25 if _PATTERNS and any(_PATTERNS[s].search(str(item.get("category", ""))) for s in mine) else 0
    title = f"{item.get('title', '')} {item.get('category', '')}".lower()
    role_words = {w for r in roles for w in re.findall(r"[a-z]{3,}", r.lower())} - {"developer", "engineer"}
    role_part = 20 if any(re.search(_ROLES[r][0], title, re.I) for r in roles if r in _ROLES) else (10 if any(w in title for w in role_words) else 0)
    exp = str(item.get("experience_required", "")).lower()
    level_part = 15
    nums = [int(n) for n in re.findall(r"\d+", exp)]
    if nums:
        low = min(nums)
        limit = {"intern": 1, "entry": 1, "junior": 3, "mid": 6, "senior": 99}.get(level, 99)
        level_part = 15 if low <= limit else max(0, 15 - 5 * (low - limit))
    elif level == "intern" and "intern" in title:
        level_part = 15
    elif level != "intern" and "intern" in title:
        level_part = 0
    score = 0 if skill_part + role_part == 0 else min(100, skill_part + role_part + level_part)   # level alone is not a match
    return {"match_score": int(round(score)), **item,
            "matched_skills": ", ".join(matched), "missing_skills": ", ".join(missing[:8])}