from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import subprocess
import json
import yaml
import os
import re
import asyncio
from datetime import datetime

from lib import db, ai, auth, crypto, mail, profile_parser, fit_score

app = FastAPI(title="Job Hunter AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on startup
@app.on_event("startup")
def startup():
    db.get_db()


# ============================================================
# Static files
# ============================================================

BASE_DIR = os.path.dirname(__file__)

@app.get("/")
async def home():
    return FileResponse(os.path.join(BASE_DIR, "templates/index.html"))


# ============================================================
# Models
# ============================================================

class SearchRequest(BaseModel):
    query: str
    location: str = "Egypt"
    remote_only: bool = False
    best_match: bool = False

class Job(BaseModel):
    id: str
    title: str
    company: str
    location: str
    remote: bool
    description: Optional[str] = ""
    apply_url: str
    source: str
    posted: Optional[str] = None
    fit_score: Optional[int] = None

class SearchResponse(BaseModel):
    jobs: List[Job]
    total: int
    query: str
    timestamp: str

class AuthRequest(BaseModel):
    username: str
    password: str

class ProfileRequest(BaseModel):
    profile: Optional[dict] = None
    cv_yaml: Optional[str] = None

class CvLoadRequest(BaseModel):
    url: str

class ChatRequest(BaseModel):
    message: str  # The new message from user
    history: list = []  # Full chat history for context

class EntryUpdate(BaseModel):
    job_id: str
    status: Optional[str] = None
    data: Optional[dict] = None

class TrackerEntryCreate(BaseModel):
    job_id: Optional[str] = None
    title: str
    company: str
    location: str = ""
    apply_url: Optional[str] = None
    source: str = "manual"
    channel: Optional[str] = None
    status: str = "saved"
    notes: str = ""
    follow_up_at: Optional[str] = None
    fit_score: Optional[int] = None
    salary: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    recruiter_phone: Optional[str] = None

class TrackerEntryUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    apply_url: Optional[str] = None
    source: Optional[str] = None
    channel: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    follow_up_at: Optional[str] = None
    fit_score: Optional[int] = None
    salary: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    recruiter_phone: Optional[str] = None
    interview_at: Optional[str] = None
    status_note: Optional[str] = None

class MailSyncRequest(BaseModel):
    account_email: Optional[str] = None
    limit: int = 50
    deep: bool = False
    stats_only: bool = False
    target_folder: Optional[str] = None
    jobs: Optional[list] = None

class AccountRequest(BaseModel):
    email: str
    password: Optional[str] = None
    enabled: bool = True

class ConfigRequest(BaseModel):
    key: str
    value: Optional[str] = None

class GenerateRequest(BaseModel):
    prompt: str
    system: Optional[str] = ""


# ============================================================
# Auth helpers
# ============================================================

def get_user(request: Request) -> dict:
    return auth.get_current_user(request)

def get_user_optional(request: Request) -> Optional[dict]:
    try:
        return auth.get_current_user(request)
    except Exception:
        return None


# ============================================================
# Auth Routes
# ============================================================

@app.post("/api/auth/signup")
async def signup(req: AuthRequest, response: Response):
    if db.get_user_by_username(req.username):
        raise HTTPException(400, "Username already exists")
    user_id = auth.generate_user_id()
    hashed = auth.hash_password(req.password)
    db.create_user(user_id, req.username, hashed)
    token = auth.create_token(user_id, req.username)
    response.set_cookie(auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=7*86400)
    return {"id": user_id, "username": req.username, "token": token}

@app.post("/api/auth/login")
async def login(req: AuthRequest, response: Response):
    user = db.get_user_by_username(req.username)
    if not user or not auth.verify_password(req.password, user["password"]):
        raise HTTPException(401, "Invalid credentials")
    token = auth.create_token(user["id"], user["username"])
    response.set_cookie(auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=7*86400)
    return {"id": user["id"], "username": user["username"], "token": token}

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}

@app.get("/api/auth/me")
async def me(request: Request):
    user = get_user(request)
    return {"id": user["id"], "username": user["username"]}


# ============================================================
# Profile Routes
# ============================================================

def calculate_profile_completeness(profile: dict) -> int:
    """Calculate profile completeness score 0-100% based on filled fields."""
    if not profile:
        return 0

    score = 0
    weights = {
        "name": 10,
        "title": 8,
        "email": 10,
        "location": 6,
        "summary": 10,
        "skills": 12,
        "experience": 15,
        "education": 8,
        "projects": 6,
        "certifications": 5,
        "languages": 4,
        "phone": 2,
        "linkedin": 2,
        "github": 2,
    }

    for field, weight in weights.items():
        val = profile.get(field)
        if val:
            if isinstance(val, str) and val.strip():
                score += weight
            elif isinstance(val, list) and len(val) > 0:
                score += weight

    # Preferences bonus (up to 10 points)
    prefs = profile.get("preferences", {})
    if prefs:
        pref_score = 0
        if prefs.get("targetRoles"):
            pref_score += 3
        if prefs.get("remotePreference"):
            pref_score += 2
        if prefs.get("experienceLevel"):
            pref_score += 2
        if prefs.get("targetLocations"):
            pref_score += 2
        if prefs.get("jobTypes"):
            pref_score += 1
        score += pref_score

    return min(score, 100)


def deep_merge(base: dict, update: dict) -> dict:
    """Deep merge update into base dict (partial update)."""
    result = base.copy()
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # Replace lists entirely (skills, experience, etc.)
            result[key] = value
        elif value is not None:
            result[key] = value
    return result


def normalize_profile(raw: dict) -> dict:
    """Ensure profile has all expected fields with correct types."""
    defaults = {
        "userId": "",
        "name": "",
        "title": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "summary": "",
        "skills": [],
        "experience": [],
        "projects": [],
        "education": [],
        "certifications": [],
        "languages": [],
        "preferences": {
            "targetRoles": [],
            "targetLocations": [],
            "remotePreference": "any",
            "experienceLevel": "any",
            "jobTypes": [],
        },
    }
    result = defaults.copy()
    result.update({k: v for k, v in raw.items() if v is not None})
    # Ensure preferences sub-object
    if "preferences" in raw and isinstance(raw["preferences"], dict):
        result["preferences"] = {**defaults["preferences"], **raw["preferences"]}
    return result


class ParseYamlRequest(BaseModel):
    yaml_content: str


@app.get("/api/profile")
async def get_profile(request: Request):
    user = get_user(request)
    doc = db.get_profile(user["id"])
    if not doc:
        return {"profile": {}, "cvYaml": "", "completeness": 0}
    profile = doc.get("profile_json", "{}")
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except Exception:
            profile = {}
    profile = normalize_profile(profile)
    completeness = calculate_profile_completeness(profile)
    return {"profile": profile, "cvYaml": doc.get("cv_yaml", ""), "completeness": completeness}


@app.post("/api/profile")
async def save_profile(req: ProfileRequest, request: Request):
    user = get_user(request)
    # Load existing profile for merge
    existing_doc = db.get_profile(user["id"])
    existing = {}
    if existing_doc:
        p = existing_doc.get("profile_json", "{}")
        existing = json.loads(p) if isinstance(p, str) else p
        if not isinstance(existing, dict):
            existing = {}

    profile = req.profile or {}
    cv_yaml = req.cv_yaml or ""

    if cv_yaml and not profile:
        profile = profile_parser.parse_cv_yaml(cv_yaml)

    # Deep merge: new data overrides existing
    merged = deep_merge(existing, profile)
    merged = normalize_profile(merged)
    merged["updatedAt"] = datetime.now().isoformat()

    db.save_profile(user["id"], merged, cv_yaml or existing_doc.get("cv_yaml", "") if existing_doc else "")
    completeness = calculate_profile_completeness(merged)
    return {"ok": True, "profile": merged, "completeness": completeness}


@app.post("/api/profile/parse-yaml")
async def parse_yaml_profile(req: ParseYamlRequest, request: Request):
    """Parse a YAML CV string and return the parsed profile without saving."""
    user = get_user(request)
    if not req.yaml_content or not req.yaml_content.strip():
        raise HTTPException(400, "yaml_content is required")

    profile = profile_parser.parse_cv_yaml(req.yaml_content)
    if not profile:
        raise HTTPException(400, "Failed to parse YAML — no data extracted")

    profile = normalize_profile(profile)
    completeness = calculate_profile_completeness(profile)
    return {"profile": profile, "completeness": completeness}

@app.post("/api/cv/load")
async def load_cv(req: CvLoadRequest, request: Request):
    user = get_user(request)
    import httpx
    try:
        resp = httpx.get(req.url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        raw_yaml = resp.text
    except Exception as e:
        raise HTTPException(400, f"Failed to fetch CV: {str(e)}")
    profile = profile_parser.parse_cv_yaml(raw_yaml)
    db.save_profile(user["id"], profile, raw_yaml)
    return {"profile": profile, "cvYaml": raw_yaml}


# ============================================================
# Search Routes
# ============================================================

SEARCH_SCRIPT = os.path.join(BASE_DIR, "hermes-search.sh")

def _parse_search_output(output: str, location: str, limit: int = 10) -> List[Job]:
    output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
    output = re.sub(r"[╭╮╰╯├┤│─]", "", output)
    output = re.sub(r"```(?:json)?\s*", "", output)

    if '"error"' in output and '"rate_limit"' in output:
        return []

    start = output.find("{")
    if start < 0:
        start = output.find("[")
    if start < 0:
        return []

    brace_count = 0
    in_string = False
    escape = False
    end = start

    for i, char in enumerate(output[start:]):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if char in "{[":
                brace_count += 1
            elif char in "}]":
                brace_count -= 1
                if brace_count == 0:
                    end = start + i + 1
                    break

    if end <= start:
        return []

    try:
        data = json.loads(output[start:end])
    except Exception:
        return []

    raw_jobs = []
    if isinstance(data, list):
        raw_jobs = data
    elif isinstance(data, dict) and "jobs" in data:
        raw_jobs = data["jobs"]

    jobs = []
    for j in raw_jobs[:limit]:
        jobs.append(Job(
            id=j.get("id", f"job-{hash(j.get('url', '') or j.get('apply_url', ''))}"),
            title=j.get("title", "Unknown"),
            company=j.get("company", "Unknown"),
            location=j.get("location", location),
            remote="remote" in j.get("location", "").lower(),
            description=j.get("description", ""),
            apply_url=j.get("url", "") or j.get("apply_url", ""),
            source=j.get("source", "Web"),
        ))
    return jobs


def _score_jobs(jobs: List[Job], profile: dict) -> List[Job]:
    """
    Score jobs using the comprehensive fit_score engine.
    """
    if not profile:
        return jobs
    
    # Convert jobs to dicts for scoring
    job_dicts = []
    for job in jobs:
        job_dict = {
            'title': job.title,
            'description': job.description or '',
            'location': job.location,
            'remote': job.remote
        }
        job_dicts.append(job_dict)
    
    # Score all jobs
    scored_dicts = fit_score.score_and_sort_jobs(job_dicts, profile)
    
    # Update job objects with scores
    for i, job in enumerate(jobs):
        if i < len(scored_dicts):
            job.fit_score = scored_dicts[i].get('fit_score', 0)
    
    # Sort jobs by fit score
    jobs.sort(key=lambda j: j.fit_score or 0, reverse=True)
    return jobs


def search_with_claude(query: str, location: str, limit: int = 10) -> List[Job]:
    """
    Search for jobs using our custom scraper that gets REAL individual job postings
    from Wuzzuf, Indeed, and other sites - NOT aggregator pages.
    Also searches free APIs (Remotive, Arbeitnow, Jobicy) for remote jobs.
    """
    import subprocess
    import json
    import os
    
    all_jobs = []
    seen_urls = set()
    
    # 1. First, try free APIs (fast, no dependencies)
    try:
        free_apis_script = os.path.join(BASE_DIR, "lib/free-apis.js")
        if os.path.exists(free_apis_script):
            print(f"[SEARCH] Calling free APIs for: {query}")
            free_result = subprocess.run(
                ["node", free_apis_script],
                input=json.dumps({"query": query, "location": location}),
                text=True,
                capture_output=True,
                timeout=15  # 15 second timeout for free APIs
            )
            
            if free_result.returncode == 0:
                free_data = json.loads(free_result.stdout)
                free_jobs = free_data.get("jobs", [])
                print(f"[SEARCH] Free APIs returned {len(free_jobs)} jobs")
                
                for job_data in free_jobs:
                    apply_url = job_data.get("applyUrl", "")
                    if apply_url and apply_url not in seen_urls and apply_url != "#":
                        seen_urls.add(apply_url)
                        all_jobs.append(Job(
                            id=job_data.get("id", f"free-{len(all_jobs)}"),
                            title=job_data.get("title", "Unknown Position")[:200],
                            company=job_data.get("company", "Unknown Company")[:100],
                            location=job_data.get("location", location)[:100],
                            remote=job_data.get("remote", True),
                            description=job_data.get("description", "")[:500],
                            apply_url=apply_url,
                            source=job_data.get("source", "Free API"),
                            posted=job_data.get("posted"),
                            fit_score=None
                        ))
            else:
                print(f"[SEARCH] Free APIs error: {free_result.stderr}")
    except Exception as e:
        print(f"[SEARCH] Free APIs exception: {e}")
    
    # 2. Then, try the main scraper (slower, more comprehensive)
    try:
        # Use the Node.js scraper we have
        script_path = "/home/vladni/Projects/job-hunter/claw-job-search.js"
        
        # Call the scraper with JSON input - focus on getting real jobs
        input_data = {
            "query": query,
            "location": location,
            "maxResults": limit * 3,  # Get more to filter
            "remoteOnly": False
        }
        
        result = subprocess.run(
            ["node", script_path],
            input=json.dumps(input_data),
            text=True,
            capture_output=True,
            timeout=55  # 55 second timeout for multi-site Firecrawl scraping
        )
        
        if result.returncode != 0:
            print(f"[SCRAPER ERROR] {result.stderr}")
            # Continue with free API results if scraper fails
        else:
            # Parse the JSON output
            data = json.loads(result.stdout)
            jobs_data = data.get("jobs", [])
            
            if jobs_data:
                # Convert to Job objects and filter for REAL individual jobs (not aggregator pages)
                for job_data in jobs_data:
                    # Skip if we've seen this URL already
                    apply_url = job_data.get("applyUrl", "")
                    if apply_url in seen_urls or not apply_url or apply_url == "#":
                        continue
                    seen_urls.add(apply_url)
                    
                    # Filter out aggregator/search pages - look for signs of individual job postings
                    title = job_data.get("title", "").lower()
                    company = job_data.get("company", "").lower()
                    
                    # Skip if it looks like a search results page
                    skip_indicators = [
                        'jobs in', 'vacancies', 'position', 'opening', 'careers', 
                        'search results', 'page', 'of', 'results', 'listing',
                        'find jobs', 'browse jobs', 'all jobs'
                    ]
                    
                    is_aggregator = any(indicator in title for indicator in skip_indicators)
                    is_aggregator = is_aggregator or ('page' in title and any(str(i) in title for i in range(1, 10)))
                    
                    # Also skip if company is generic like "Apply via link" or "Hiring Company"
                    if company in ['apply via link', 'hiring company', 'unknown company', '']:
                        is_aggregator = True
                    
                    # Only add if it looks like a REAL individual job posting
                    if not is_aggregator and len(title) > 10 and len(company) > 2:
                        all_jobs.append(Job(
                            id=job_data.get("id", f"job-{len(all_jobs)}"),
                            title=job_data.get("title", "Unknown Position")[:200],
                            company=job_data.get("company", "Unknown Company")[:100],
                            location=job_data.get("location", location)[:100],
                            remote=job_data.get("remote", False),
                            description=job_data.get("description", "")[:500],
                            apply_url=apply_url,
                            source=job_data.get("source", "Job Board"),
                            posted=job_data.get("posted"),
                            fit_score=None
                        ))
                
    except subprocess.TimeoutExpired:
        print("[SCRAPER ERROR] Timeout scraping jobs")
    except json.JSONDecodeError as e:
        print(f"[SCRAPER ERROR] Invalid JSON from scraper: {e}")
    except Exception as e:
        print(f"[SCRAPER ERROR] {e}")
    
    # Return up to limit jobs
    return all_jobs[:limit]


def search_background(query: str, location: str):
    # Disabled for now - just logging
    print(f"[BACKGROUND] Would search for {query} in {location}")
    # jobs = search_with_claude(query, location, 30)
    # if jobs:
    #     db.cache_jobs([j.model_dump() for j in jobs], query, location)


@app.post("/api/search", response_model=SearchResponse)
async def search_jobs(req: SearchRequest, request: Request):
    query = req.query
    location = req.location
    user = get_user_optional(request)

    print(f"[API] Search request: query={query}, location={location}, remote_only={req.remote_only}, best_match={req.best_match}")

    # Try cache first
    cached = db.get_cached_jobs(query, location)
    if cached:
        print(f"[API] Returning {len(cached)} cached jobs")
        jobs = []
        for doc in cached[:10]:
            jobs.append(Job(
                id=str(doc.get("id", doc.get("_id", ""))),
                title=doc.get("title", "Unknown"),
                company=doc.get("company", "Unknown"),
                location=doc.get("location", location),
                remote=doc.get("remote", False),
                description=doc.get("description", ""),
                apply_url=doc.get("apply_url", "") or doc.get("url", ""),
                source=doc.get("source", "Web"),
            ))
        if req.best_match and user:
            profile_doc = db.get_profile(user["id"])
            if profile_doc:
                p = json.loads(profile_doc.get("profile_json", "{}"))
                jobs = _score_jobs(jobs, p)
        if req.remote_only:
            jobs = [j for j in jobs if j.remote]
        return SearchResponse(jobs=jobs, total=len(jobs), query=f"{query} in {location}", timestamp=datetime.now().isoformat())

    # Live search
    jobs = search_with_claude(query, location, 10)

    # Background fetch more
    asyncio.create_task(asyncio.to_thread(search_background, query, location))

    # Score if best match
    if req.best_match and user:
        profile_doc = db.get_profile(user["id"])
        if profile_doc:
            p = json.loads(profile_doc.get("profile_json", "{}"))
            jobs = _score_jobs(jobs, p)

    if req.remote_only:
        jobs = [j for j in jobs if j.remote]

    # Cache results
    if jobs:
        db.cache_jobs([j.model_dump() for j in jobs], query, location)

    return SearchResponse(
        jobs=jobs, total=len(jobs),
        query=f"{query} in {location}",
        timestamp=datetime.now().isoformat()
    )


# ============================================================
# Tracker Routes
# ============================================================

@app.get("/api/jobs")
async def get_jobs(request: Request):
    user = get_user(request)
    entries = db.get_entries(user["id"])
    return {"entries": entries}

@app.post("/api/jobs")
async def create_job(req: TrackerEntryCreate, request: Request):
    user = get_user(request)
    if not req.title or not req.title.strip():
        raise HTTPException(400, "title is required")
    if not req.company or not req.company.strip():
        raise HTTPException(400, "company is required")

    now = datetime.now().isoformat()
    job_id = req.job_id or f"manual-{int(datetime.now().timestamp() * 1000)}"

    entry = {
        "userId": user["id"],
        "jobId": job_id,
        "title": req.title.strip(),
        "company": req.company.strip(),
        "location": req.location or "",
        "applyUrl": req.apply_url or "",
        "source": req.source,
        "channel": req.channel or "",
        "status": req.status,
        "statusHistory": [{"status": req.status, "timestamp": now}],
        "appliedAt": now if req.status == "applied" else "",
        "interviewAt": "",
        "recruiterName": req.recruiter_name or "",
        "recruiterEmail": req.recruiter_email or "",
        "recruiterPhone": req.recruiter_phone or "",
        "notes": req.notes or "",
        "coverLetterId": "",
        "cvVersion": "",
        "followUpAt": req.follow_up_at or "",
        "reminderSent": False,
        "emailThreadIds": [],
        "fitScore": req.fit_score,
        "salary": req.salary or "",
        "needsReview": False,
        "createdAt": now,
        "updatedAt": now,
    }

    db.create_entry(user["id"], job_id, entry)
    return {"ok": True, "entry": entry}

@app.put("/api/jobs/{entry_id}")
async def update_job_entry(entry_id: str, req: TrackerEntryUpdate, request: Request):
    user = get_user(request)
    existing = db.get_entry(user["id"], entry_id)
    if not existing:
        raise HTTPException(404, "Entry not found")

    now = datetime.now().isoformat()
    update_data = {}

    if req.title is not None:
        update_data["title"] = req.title
    if req.company is not None:
        update_data["company"] = req.company
    if req.location is not None:
        update_data["location"] = req.location
    if req.apply_url is not None:
        update_data["applyUrl"] = req.apply_url
    if req.source is not None:
        update_data["source"] = req.source
    if req.channel is not None:
        update_data["channel"] = req.channel
    if req.notes is not None:
        update_data["notes"] = req.notes
    if req.follow_up_at is not None:
        update_data["followUpAt"] = req.follow_up_at
    if req.fit_score is not None:
        update_data["fitScore"] = req.fit_score
    if req.salary is not None:
        update_data["salary"] = req.salary
    if req.recruiter_name is not None:
        update_data["recruiterName"] = req.recruiter_name
    if req.recruiter_email is not None:
        update_data["recruiterEmail"] = req.recruiter_email
    if req.recruiter_phone is not None:
        update_data["recruiterPhone"] = req.recruiter_phone
    if req.interview_at is not None:
        update_data["interviewAt"] = req.interview_at

    # On status change, append to statusHistory
    if req.status is not None and req.status != existing.get("status"):
        update_data["status"] = req.status
        history = existing.get("statusHistory", [])
        history.append({"status": req.status, "timestamp": now, "note": req.status_note or ""})
        update_data["statusHistory"] = history
        if req.status == "applied" and not existing.get("appliedAt"):
            update_data["appliedAt"] = now
        if req.status == "interview" and not existing.get("interviewAt"):
            update_data["interviewAt"] = now

    update_data["updatedAt"] = now
    db.update_entry_fields(user["id"], entry_id, update_data)
    return {"ok": True}

@app.delete("/api/jobs/{entry_id}")
async def delete_job(entry_id: str, request: Request):
    user = get_user(request)
    db.delete_entry(user["id"], entry_id)
    return {"ok": True}

@app.get("/api/jobs/{entry_id}/emails")
async def get_entry_emails(entry_id: str, request: Request):
    user = get_user(request)
    entry = db.get_entry(user["id"], entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    thread_ids = entry.get("emailThreadIds", [])
    if not thread_ids:
        return {"emails": []}
    messages = db.get_vault_by_thread_ids(user["id"], thread_ids)
    return {"emails": messages}


# ============================================================
# Email Routes
# ============================================================

@app.post("/api/mail")
async def sync_email(req: MailSyncRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    accounts = db.get_accounts(user["id"])

    if not accounts:
        raise HTTPException(400, "No email accounts configured")

    all_matches = []
    all_stats = {}

    target_accounts = accounts
    if req.account_email:
        target_accounts = [a for a in accounts if a["email"] == req.account_email]

    # Get tracked jobs for matching
    entries = db.get_entries(user["id"])
    jobs = req.jobs or []
    for entry in entries:
        d = entry.get("data_json", {})
        if isinstance(d, str):
            d = json.loads(d)
        jobs.append({
            "jobId": entry.get("jobId", ""),
            "company": d.get("company", ""),
            "title": d.get("title", "")
        })

    for account in target_accounts:
        if not account.get("enabled", True):
            continue
        result = mail.sync_mail(
            user_id=user["id"],
            account_email=account["email"],
            account_pass=account.get("pass", ""),
            jobs=jobs,
            limit=req.limit,
            deep=req.deep,
            stats_only=req.stats_only,
            target_folder=req.target_folder,
            user_config=user_config
        )
        all_matches.extend(result.get("matches", []))
        all_stats[account["email"]] = result.get("stats", {})

    return {"matches": all_matches, "stats": all_stats, "aiActive": bool(user_config.get("GROQ_API_KEY"))}


@app.get("/api/vault")
async def get_vault(request: Request, limit: int = 100, folder: str = None):
    user = get_user(request)
    messages = db.get_vault(user["id"], limit, folder)
    return {"messages": messages}


@app.get("/api/accounts")
async def get_accounts(request: Request):
    user = get_user(request)
    accounts = db.get_accounts(user["id"])
    # Strip passwords from response
    return {"accounts": [{"email": a["email"], "enabled": a.get("enabled", True)} for a in accounts]}

@app.post("/api/accounts")
async def add_account(req: AccountRequest, request: Request):
    user = get_user(request)
    value = json.dumps({"pass": crypto.encrypt(req.password) if req.password else "", "enabled": req.enabled})
    db.set_config(user["id"], f"account:{req.email}", value)
    return {"ok": True}

@app.delete("/api/accounts/{email}")
async def delete_account(email: str, request: Request):
    user = get_user(request)
    db.delete_config(user["id"], f"account:{email}")
    return {"ok": True}


# ============================================================
# Chat Route - Unified AI Job Hunter
# ============================================================

@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    # Require authenticated user from JWT cookie
    user = get_user(request)

    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    user_message = req.message
    history = req.history or []
    
    # Smart intent extraction — understands natural language without AI
    jobs = []
    response_text = ""
    message_lower = user_message.lower().strip()
    
    # Strip leading greetings
    greeting_stripped = re.sub(r'^(hi+|hello|hey|yo|sup|what\'?s?\s*up|good\s*(morning|afternoon|evening))[\s,!.\-]*', '', message_lower).strip()
    
    # Location detection — from message first, then profile/CV
    location = None  # Don't default — let profile or user decide
    
    # Common location names to detect in messages
    location_map = {
        'cairo': 'Cairo', 'giza': 'Giza', 'alexandria': 'Alexandria',
        'remote': 'Remote', 'dubai': 'Dubai', 'uk': 'UK', 'usa': 'USA', 'uae': 'UAE',
        'gcc': 'GCC', 'gulf': 'Gulf', 'saudi': 'Saudi Arabia',
        'qatar': 'Qatar', 'kuwait': 'Kuwait', 'bahrain': 'Bahrain',
        'egypt': 'Egypt', 'jordan': 'Jordan', 'lebanon': 'Lebanon',
        'oman': 'Oman', 'morocco': 'Morocco', 'tunisia': 'Tunisia',
        'germany': 'Germany', 'france': 'France', 'canada': 'Canada',
        'europe': 'Europe', 'africa': 'Africa', 'asia': 'Asia',
    }
    for key, val in location_map.items():
        if key in greeting_stripped or key in message_lower:
            location = val
            break
    
    # Fall back to profile location
    if not location and profile:
        location = profile.get("location", "") or profile.get("city", "") or profile.get("country", "")
    
    # Final fallback
    if not location:
        location = ""  # Let the scraper decide — don't force a country
    
    # Intent detection on the greeting-stripped text
    intent = "chat"
    job_title = ""
    
    # Check for job search intent
    job_triggers = ['find', 'search', 'looking for', 'need', 'want', 'hire', 'hiring', 'apply', 'job', 'jobs', 'career', 'position', 'vacancy', 'opening']
    has_job_trigger = any(t in greeting_stripped for t in job_triggers)
    
    # Known job roles (order matters — longer matches first)
    known_roles = [
        'data engineer', 'data analyst', 'data scientist', 'software engineer', 'software developer',
        'full stack', 'fullstack', 'frontend developer', 'backend developer', 'front end', 'back end',
        'devops engineer', 'machine learning', 'ai engineer', 'mobile developer',
        'graphic designer', 'ui designer', 'ux designer', 'web designer',
        'product manager', 'project manager', 'marketing manager', 'sales manager',
        'account manager', 'operations manager', 'hr manager',
        'digital marketing', 'social media', 'content writer', 'seo specialist',
        'financial analyst', 'business analyst', 'system analyst',
        'accountant', 'nurse', 'doctor', 'teacher', 'lawyer', 'architect',
        'civil engineer', 'mechanical engineer', 'electrical engineer',
        'sales representative', 'customer service', 'receptionist',
        'developer', 'engineer', 'designer', 'analyst', 'manager',
        'consultant', 'specialist', 'coordinator', 'administrator',
        'marketing', 'finance', 'hr', 'admin', 'logistics', 'procurement',
        'warehouse', 'driver', 'security', 'chef', 'waiter', 'cashier',
    ]
    
    # Find the role in the message
    for role in known_roles:
        if role in greeting_stripped:
            job_title = role
            intent = "job_search"
            break
    
    # If no known role found but has job trigger, extract noun-ish words
    if intent == "job_search" and not job_title:
        # Remove filler words
        filler = {'i', 'me', 'a', 'an', 'the', 'some', 'any', 'find', 'search', 'for', 'in', 'at', 'near',
                  'jobs', 'job', 'position', 'positions', 'vacancy', 'vacancies', 'opening', 'openings',
                  'work', 'career', 'careers', 'please', 'plz', 'pls', 'can', 'could', 'would',
                  'like', 'want', 'need', 'am', 'im', "i'm", 'looking', 'seeking', 'hunting',
                  'get', 'give', 'show', 'tell', 'help', 'me', 'us'}
        words = greeting_stripped.split()
        role_words = [w for w in words if w not in filler and len(w) > 1 and not w.isdigit()]
        if role_words:
            job_title = ' '.join(role_words[:4])  # Max 4 words
    
    # Non-job intents
    if intent == "chat":
        if any(w in greeting_stripped for w in ['interview', 'prep', 'practice', 'mock', 'questions']):
            intent = "interview_prep"
        elif any(w in greeting_stripped for w in ['cv', 'resume', 'review', 'feedback', 'ats']):
            intent = "cv_review"
        elif any(w in greeting_stripped for w in ['cover letter', 'application letter', 'write a letter']):
            intent = "cover_letter"
        elif any(w in greeting_stripped for w in ['how do i answer', 'what should i say', 'application question']):
            intent = "application_answer"
        elif any(w in greeting_stripped for w in ['i applied', 'applied to', 'add to tracker', 'track this', 'i got']):
            intent = "tracker_add"
        elif any(w in greeting_stripped for w in ['salary', 'how much', 'pay', 'compensation', 'how much do']):
            intent = "salary_info"
        elif any(w in greeting_stripped for w in ['analytics', 'stats', 'how am i doing', 'response rate', 'progress']):
            intent = "analytics"
    
    print(f"[CHAT] Intent: {intent}, job_title: '{job_title}', location: '{location}'")
    
    if intent == "job_search" and job_title:
        
        # Search for jobs using Hermes
        found_jobs = search_with_claude(job_title, location, limit=10)
        
        if found_jobs:
            jobs = [j.dict() for j in found_jobs]
            sources = set(j.get("source", "") for j in jobs if j.get("source"))
            source_str = ", ".join(sorted(sources)) if sources else "multiple sites"
            loc_str = f" in {location}" if location else ""
            response_text = f"Found {len(jobs)} {job_title} jobs{loc_str} from {source_str}."
        else:
            loc_str = f" in {location}" if location else ""
            response_text = f"No {job_title} jobs found{loc_str}. Try a different search term or location."
    
    elif intent == "interview_prep":
        response_text = await ai.interview_prep(user_message, profile, user_config)

    elif intent == "cv_review":
        # Run ATS check on their profile
        ats_result = _check_ats_internal(profile, None)
        score = ats_result["score"]
        issues = ats_result["issues"]
        issue_text = "\n".join(f"  • [{i['severity']}] {i['message']}" for i in issues[:5])
        response_text = f"Your CV scores {score}/100 for ATS compatibility.\n\nTop issues:\n{issue_text}\n\nUse the CV tab to see full details and fix issues."

    elif intent == "cover_letter":
        response_text = "I can write a cover letter for you. Tell me:\n1. What job title?\n2. What company?\n3. Paste the job description (optional but recommended)\n\nOr use the 'Generate Cover Letter' button on any job card."

    elif intent == "application_answer":
        response_text = "I can help you answer application questions. Tell me:\n1. What's the question?\n2. What company/role is it for?\n\nCommon questions I handle: 'Tell me about yourself', 'Why this company?', 'Salary expectation', 'Notice period'."

    elif intent == "tracker_add":
        # Extract company name from message
        company = greeting_stripped
        for remove in ['i applied to', 'applied to', 'add to tracker', 'track this', 'i got', 'a job at', 'an interview at', 'at']:
            company = company.replace(remove, '').strip()
        company = company.split()[0].capitalize() if company else "Unknown"
        response_text = f"I've noted you applied to {company}. Use the Tracker tab to add full details (title, status, dates). I can also help you track follow-ups."

    elif intent == "salary_info":
        role = job_title or "your role"
        response_text = f"I can look up salary ranges for {role}. What location are you targeting? This helps me give accurate figures."

    elif intent == "analytics":
        response_text = "Check the Tracker tab for your application analytics — response rates, velocity, and source performance. I can also pull up specific stats if you ask."

    else:
        response_text = await ai.chat_general(user_message, profile, user_config, history)

    return {"text": response_text, "jobs": jobs}


# ============================================================
# Config Route
# ============================================================

@app.get("/api/config")
async def get_config(request: Request):
    user = get_user(request)
    cfg = db.get_config(user["id"])
    # Don't expose encrypted values directly, just show which keys are set
    safe = {}
    for k, v in cfg.items():
        if k.startswith("account:"):
            continue
        safe[k] = "***" if any(secret in k.upper() for secret in ["KEY", "PASS", "SECRET"]) else v
    return {"config": safe}

@app.post("/api/config")
async def set_config(req: ConfigRequest, request: Request):
    user = get_user(request)
    if req.value is None:
        db.delete_config(user["id"], req.key)
    else:
        value = req.value
        if any(secret in req.key.upper() for secret in ["KEY", "PASS", "SECRET"]):
            value = crypto.encrypt(value)
        db.set_config(user["id"], req.key, value)
    return {"ok": True}


# ============================================================
# Generate Route
# ============================================================

@app.post("/api/generate")
async def generate(req: GenerateRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    system = req.system or ""
    if profile:
        system += f"\n\nCandidate: {profile.get('name', '')}, {profile.get('title', '')}\nSkills: {', '.join(profile.get('skills', [])[:20])}"

    text = ai.generate_text(req.prompt, system, user_config)
    return {"text": text}


# ============================================================
# Onboarding — AI-Powered CV Upload
# ============================================================

import secrets
import string as _string

def _normalize_cv_yaml(data: dict) -> dict:
    """Normalize various YAML CV formats into our profile structure"""
    profile = {}

    # Handle RenderCV format
    cv = data.get("cv", data)

    # Name
    profile["name"] = cv.get("name", data.get("name", ""))

    # Contact info
    if isinstance(cv.get("contact"), dict):
        contact = cv["contact"]
        profile["email"] = contact.get("email", "")
        profile["phone"] = contact.get("phone", "")
        profile["location"] = contact.get("location", contact.get("address", ""))
        profile["linkedin"] = contact.get("linkedin", contact.get("url", ""))
        profile["github"] = contact.get("github", "")
    elif isinstance(cv.get("contact"), list):
        for item in cv["contact"]:
            if isinstance(item, dict) and "email" in item:
                profile["email"] = item["email"]
            elif isinstance(item, str) and "@" in item:
                profile["email"] = item

    # Sections
    sections = cv.get("sections", cv.get("experience", []))
    if isinstance(sections, list):
        profile["experience"] = []
        profile["education"] = []
        profile["skills"] = []
        profile["summary"] = ""

        for section in sections:
            if not isinstance(section, dict):
                continue

            section_type = section.get("type", section.get("title", "")).lower()

            if "experience" in section_type or "work" in section_type:
                for entry in section.get("entries", section.get("items", [])):
                    if isinstance(entry, dict):
                        exp = {
                            "role": entry.get("title", entry.get("role", "")),
                            "company": entry.get("company", entry.get("employer", "")),
                            "location": entry.get("location", ""),
                            "startDate": str(entry.get("start_date", entry.get("startDate", ""))),
                            "endDate": str(entry.get("end_date", entry.get("endDate", "Present"))),
                            "highlights": entry.get("highlights", entry.get("details", [])),
                        }
                        if exp["role"]:
                            profile["experience"].append(exp)

            elif "education" in section_type:
                for entry in section.get("entries", section.get("items", [])):
                    if isinstance(entry, dict):
                        edu = {
                            "degree": entry.get("degree", ""),
                            "field": entry.get("area", entry.get("field", "")),
                            "institution": entry.get("institution", entry.get("university", "")),
                            "startYear": entry.get("start_date", entry.get("startYear", 0)),
                            "endYear": entry.get("end_date", entry.get("endYear", None)),
                        }
                        if edu["institution"]:
                            profile["education"].append(edu)

            elif "skill" in section_type:
                items = section.get("items", section.get("entries", section.get("skills", [])))
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, str):
                            profile["skills"].append(item)
                        elif isinstance(item, dict):
                            # e.g. {languages: ["Python", "Java"]}
                            for v in item.values():
                                if isinstance(v, list):
                                    profile["skills"].extend(v)
                                elif isinstance(v, str):
                                    profile["skills"].append(v)

            elif "summary" in section_type or "objective" in section_type:
                text = section.get("text", section.get("content", ""))
                if isinstance(text, list):
                    text = " ".join(text)
                profile["summary"] = str(text)

            elif "certification" in section_type:
                items = section.get("items", section.get("entries", []))
                profile["certifications"] = [str(i) for i in items] if isinstance(items, list) else []

    # Top-level fields (RenderCV format)
    if isinstance(cv.get("education"), list):
        for entry in cv["education"]:
            if isinstance(entry, dict) and entry not in profile.get("education", []):
                profile.setdefault("education", []).append(entry)

    if isinstance(cv.get("skills"), (list, dict)):
        if isinstance(cv["skills"], list):
            for s in cv["skills"]:
                if isinstance(s, str) and s not in profile.get("skills", []):
                    profile.setdefault("skills", []).append(s)
                elif isinstance(s, dict):
                    for v in s.values():
                        if isinstance(v, list):
                            profile.setdefault("skills", []).extend(v)

    # Title from first experience or summary
    if not profile.get("title") and profile.get("experience"):
        profile["title"] = profile["experience"][0].get("role", "")

    # Clean empty lists
    for k in ["skills", "experience", "education", "certifications"]:
        if k in profile and isinstance(profile[k], list):
            profile[k] = [x for x in profile[k] if x]

    return profile


def _extract_profile_regex(text: str) -> dict:
    """Regex-based profile extraction as last resort"""
    import re as _re
    profile = {"skills": [], "experience": [], "education": [], "certifications": []}

    # Email
    email_match = _re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    if email_match:
        profile["email"] = email_match.group(0)

    # Phone
    phone_match = _re.search(r'[\+]?[\d\s\-\(\)]{8,15}', text)
    if phone_match:
        profile["phone"] = phone_match.group(0).strip()

    # Name — usually the first line or first bold/uppercase line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines[:5]:
        # Name is usually short, capitalized, no numbers
        if 3 < len(line) < 50 and not _re.search(r'[\d@]', line) and not any(w in line.lower() for w in ['resume', 'cv', 'curriculum', 'phone', 'email', 'address', 'linkedin', 'github']):
            words = line.split()
            if 1 < len(words) < 5 and all(w[0].isupper() for w in words if w):
                profile["name"] = line
                break

    # Location
    loc_match = _re.search(r'(Cairo|Giza|Alexandria|Egypt|Dubai|UAE|Saudi|London|New York|Remote)[^\n]{0,30}', text, _re.IGNORECASE)
    if loc_match:
        profile["location"] = loc_match.group(0).strip()

    # Skills — look for common tech terms
    tech_skills = ['python', 'sql', 'java', 'javascript', 'typescript', 'react', 'node', 'aws', 'azure',
                   'docker', 'kubernetes', 'mongodb', 'postgresql', 'excel', 'power bi', 'tableau',
                   'pandas', 'numpy', 'git', 'linux', 'fastapi', 'django', 'flask', 'spark', 'airflow']
    text_lower = text.lower()
    profile["skills"] = [s.title() for s in tech_skills if s in text_lower]

    return profile


def _generate_username(name: str) -> str:
    """Generate a username from a name like 'Ossama Taha' -> 'ossama.taha.8472'"""
    import re as _re
    clean = _re.sub(r'[^a-z\s]', '', name.lower()).strip()
    parts = clean.split()
    if len(parts) >= 2:
        base = f"{parts[0]}.{parts[-1]}"
    else:
        base = parts[0] if parts else "user"
    suffix = ''.join(secrets.choice(_string.digits) for _ in range(4))
    return f"{base}.{suffix}"

def _generate_password(length=12) -> str:
    """Generate a random password"""
    alphabet = _string.ascii_letters + _string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@app.post("/api/onboarding/upload-cv")
async def onboard_upload_cv(request: Request):
    """Upload a CV file (PDF, YAML, MD) and auto-create profile from it"""
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No file uploaded")

    filename = file.filename or "cv"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Extract text from file
    raw_text = ""
    if ext == "pdf":
        import tempfile, os
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            import pdfplumber
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    raw_text += (page.extract_text() or "") + "\n"
        finally:
            os.unlink(tmp_path)
    elif ext in ("yaml", "yml", "md", "txt"):
        content = await file.read()
        raw_text = content.decode("utf-8", errors="replace")
    else:
        raise HTTPException(400, f"Unsupported file type: .{ext}. Use PDF, YAML, MD, or TXT.")

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from file")

    profile = {}

    # Strategy 1: Direct YAML parsing (for YAML/YML files)
    if ext in ("yaml", "yml"):
        try:
            yaml_data = yaml.safe_load(raw_text)
            if isinstance(yaml_data, dict):
                profile = _normalize_cv_yaml(yaml_data)
                print(f"[ONBOARD] Parsed YAML directly: {profile.get('name', 'unknown')}")
        except Exception as e:
            print(f"[ONBOARD] YAML parse failed: {e}")

    # Strategy 2: AI extraction (for PDF, MD, TXT, or if YAML parsing didn't get enough)
    if not profile.get("name"):
        system = """Extract a structured profile from this CV/resume text. Return JSON only:
{
  "name": "Full Name",
  "title": "Current or target job title",
  "email": "email@example.com",
  "phone": "+1234567890",
  "location": "City, Country",
  "linkedin": "linkedin.com/in/username",
  "github": "github.com/username",
  "summary": "2-3 sentence professional summary",
  "skills": ["skill1", "skill2"],
  "experience": [{"role": "Title", "company": "Company", "startDate": "2022", "endDate": "2024", "highlights": ["achievement"]}],
  "education": [{"degree": "Bachelor's", "field": "CS", "institution": "Uni", "startYear": 2020, "endYear": 2024}],
  "certifications": [], "languages": [], "preferences": {"targetRoles": [], "remotePreference": "any", "experienceLevel": "mid"}
}
Extract ALL info. Never fabricate. Empty string/arrays for missing fields."""

        ai_result = ai.ask_ai(f"Extract profile from this CV:\n\n{raw_text[:4000]}", system, max_tokens=2500, force_json=True)
        if ai_result and ai_result.strip():
            try:
                ai_profile = json.loads(ai_result)
                # Merge AI profile into existing (AI takes priority for non-empty fields)
                for k, v in ai_profile.items():
                    if v and (not profile.get(k) or (isinstance(v, list) and len(v) > 0)):
                        profile[k] = v
            except Exception as e:
                print(f"[ONBOARD] AI JSON parse failed: {e}")

    # Strategy 3: Regex fallback (extract name, email, phone from raw text)
    if not profile.get("name"):
        profile = _extract_profile_regex(raw_text)

    if not profile.get("name"):
        raise HTTPException(400, "Could not extract name from CV. Try a different file format.")

    # Ensure required fields
    name = profile.get("name", "")
    if not name:
        raise HTTPException(400, "Could not extract name from CV. Please try a clearer file.")

    # Generate credentials
    username = _generate_username(name)
    password = _generate_password(10)

    # Check if user already exists (by cookie)
    existing_user = get_user_optional(request)
    if existing_user:
        user_id = existing_user["id"]
        # Update existing user's username if needed
    else:
        # Create new user with generated credentials
        user_id = auth.generate_user_id()
        hashed = auth.hash_password(password)
        try:
            db.create_user(user_id, username, hashed)
        except:
            # Username collision — regenerate
            username = _generate_username(name)
            db.create_user(user_id, username, hashed)

        # Set auth cookie
        from starlette.responses import JSONResponse
        token = auth.create_token(user_id, username)

    # Save profile
    profile["userId"] = user_id
    profile["updatedAt"] = datetime.now().isoformat()
    db.save_profile(user_id, profile)

    # Set auth cookie in response
    response_data = {
        "success": True,
        "username": username,
        "password": password,
        "profile": {
            "name": profile.get("name", ""),
            "title": profile.get("title", ""),
            "skills": profile.get("skills", [])[:10],
            "experience": len(profile.get("experience", [])),
        },
        "message": "Profile created from your CV. Save your credentials — you'll need them to log in."
    }

    response = JSONResponse(response_data)
    if not existing_user:
        response.set_cookie(auth.COOKIE_NAME, token, httponly=True, samesite="lax", max_age=30*86400)
    return response


@app.post("/api/onboarding/generate-credentials")
async def generate_credentials(request: Request):
    """Generate new credentials for the current user"""
    user = get_user(request)
    new_password = _generate_password(10)
    hashed = auth.hash_password(new_password)
    db.update_user_password(user["id"], hashed)
    return {"password": new_password, "message": "New password generated. Save it!"}


# ============================================================
# Phase 5 — AI Generation Tools
# ============================================================

class CoverLetterRequest(BaseModel):
    job_title: str
    company: str
    job_description: str = ""
    tone: str = "formal"  # formal / friendly / direct
    length: str = "standard"  # short / standard / detailed

@app.post("/api/generate/cover-letter")
async def generate_cover_letter(req: CoverLetterRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    name = profile.get("name", "the candidate")
    title = profile.get("title", "professional")
    location = profile.get("location", "")
    summary = profile.get("summary", "")
    skills = ", ".join(profile.get("skills", [])[:15])
    exp = profile.get("experience", [])
    top_exp = ""
    for e in exp[:2]:
        highlights = "; ".join(e.get("highlights", [])[:3])
        top_exp += f"\n- {e.get('role', '')} at {e.get('company', '')}: {highlights}"

    length_guide = {"short": "~150 words", "standard": "~300 words", "detailed": "~500 words"}
    word_target = length_guide.get(req.length, "~300 words")

    system = f"""You are writing a cover letter. Use REAL data only — no placeholders.

Candidate: {name}, {title} based in {location}
Summary: {summary}
Skills: {skills}
Experience:{top_exp}

Target role: {req.job_title} at {req.company}
Job description: {req.job_description[:800]}

Write a {word_target} cover letter in a {req.tone} tone.
- Start with a strong hook, NOT "I am writing to apply"
- Reference 2-3 specific skills/experiences that match the role
- End with a clear call to action
- NO placeholders like [Your Name] — use actual data
- Output the letter text only"""

    text = ai.generate_text(f"Write a cover letter for {req.job_title} at {req.company}", system, user_config)
    return {"text": text, "wordCount": len(text.split())}


class QARequest(BaseModel):
    question: str
    company: str = ""
    job_title: str = ""
    max_words: int = 150

@app.post("/api/generate/qa-answer")
async def generate_qa_answer(req: QARequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    exp = profile.get("experience", [])
    exp_summary = ""
    for e in exp[:3]:
        highlights = "; ".join(e.get("highlights", [])[:3])
        exp_summary += f"\n- {e.get('role', '')} at {e.get('company', '')}: {highlights}"

    system = f"""You are helping a job candidate answer interview questions. Use REAL data from their profile.

Candidate: {profile.get('name', 'Candidate')}, {profile.get('title', 'professional')}
Skills: {', '.join(profile.get('skills', [])[:15])}
Experience:{exp_summary}
Salary preference: {profile.get('preferences', {}).get('salaryMin', 'Not specified')}
Notice period: {profile.get('preferences', {}).get('noticePeriod', 'Not specified')}

Target role: {req.job_title} at {req.company}
Max {req.max_words} words. Be specific, use real examples, no generic advice."""

    text = ai.generate_text(f"Answer this interview question: {req.question}", system, user_config)
    return {"answer": text}


class FollowUpRequest(BaseModel):
    entry_id: str
    type: str = "follow_up"  # follow_up / thank_you / withdraw

@app.post("/api/generate/follow-up")
async def generate_follow_up(req: FollowUpRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    # Load tracker entry
    entry = db.get_entry(user["id"], req.entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    company = entry.get("company", "the company")
    job_title = entry.get("title", "the position")
    applied_date = entry.get("appliedAt", "recently")

    type_prompts = {
        "follow_up": f"Write a polite follow-up email about my application for {job_title} at {company}, applied {applied_date}. Brief, professional, reiterate interest.",
        "thank_you": f"Write a thank-you email after interviewing for {job_title} at {company}. Reference specific points from the interview, express enthusiasm.",
        "withdraw": f"Write a professional withdrawal email for my application for {job_title} at {company}. Gracious, brief, leave door open."
    }

    system = f"""Write a professional email. Use real candidate data.
Candidate: {profile.get('name', 'Candidate')}, {profile.get('title', 'professional')}
Return format: Subject: <subject line>\n\n<body>"""

    text = ai.generate_text(type_prompts.get(req.type, type_prompts["follow_up"]), system, user_config)
    lines = text.strip().split("\n", 1)
    subject = lines[0].replace("Subject:", "").strip() if lines else f"Follow-up: {job_title}"
    body = lines[1].strip() if len(lines) > 1 else text
    return {"subject": subject, "body": body}


class TailorCVRequest(BaseModel):
    job_description: str

@app.post("/api/generate/tailor-cv")
async def tailor_cv(req: TailorCVRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    exp = profile.get("experience", [])
    all_bullets = []
    for e in exp:
        for h in e.get("highlights", []):
            all_bullets.append(f"[{e.get('role', '')} @ {e.get('company', '')}] {h}")

    bullets_text = "\n".join(all_bullets[:30])

    system = """You are a CV optimization expert. Analyze the job description and suggest specific improvements.
Return JSON only:
{
  "reorderedBullets": [{"original": "...", "suggested": "...", "reason": "..."}],
  "keywordsToAdd": ["keyword1", "keyword2"],
  "sectionsToEmphasize": ["section1"],
  "estimatedATSScore": 75
}"""

    prompt = f"""Job Description:
{req.job_description[:1000]}

Current CV Bullets:
{bullets_text}

Candidate Skills: {', '.join(profile.get('skills', [])[:20])}

Analyze and return suggestions as JSON."""

    result = ai.ask_ai(prompt, system, user_config, max_tokens=1500, force_json=True)
    try:
        data = json.loads(result)
    except:
        data = {"reorderedBullets": [], "keywordsToAdd": [], "sectionsToEmphasize": [], "estimatedATSScore": 50, "raw": result}
    return data


# ============================================================
# Phase 7 — Interview Preparation
# ============================================================

class InterviewQuestionRequest(BaseModel):
    role: str
    level: str = "mid"  # junior / mid / senior
    count: int = 10
    types: list = ["behavioral", "technical", "situational"]

@app.post("/api/interview/questions")
async def get_interview_questions(req: InterviewQuestionRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])

    # Check cache
    cache_key = f"questions:{req.role}:{req.level}"
    cached = db.get_cached_data(cache_key)
    if cached:
        return {"questions": cached[:req.count]}

    type_str = ", ".join(req.types)
    system = f"""Generate interview questions for a {req.level} {req.role} position.
Return JSON array: [{{"question": "...", "type": "behavioral|technical|situational|company", "hint": "what a good answer covers"}}]
Generate {req.count} questions. Types: {type_str}.
Technical questions must be specific to {req.role} tools and concepts.
Return ONLY the JSON array."""

    result = ai.ask_ai(f"Generate {req.count} interview questions for {req.level} {req.role}", system, user_config, max_tokens=2000, force_json=True)
    try:
        questions = json.loads(result)
    except:
        questions = [{"question": f"Tell me about your experience with {req.role} work", "type": "behavioral", "hint": "Use specific examples from your career"}]

    # Cache for 7 days
    db.cache_data(cache_key, questions, ttl_seconds=7*24*3600)
    return {"questions": questions[:req.count]}


class STARRequest(BaseModel):
    question: str
    context: str = ""

@app.post("/api/interview/star-answer")
async def generate_star_answer(req: STARRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    exp = profile.get("experience", [])
    exp_text = ""
    for e in exp[:3]:
        highlights = "\n    - ".join(e.get("highlights", [])[:4])
        exp_text += f"\n  {e.get('role', '')} at {e.get('company', '')}:\n    - {highlights}"

    system = f"""You are building a STAR (Situation, Task, Action, Result) answer for an interview question.
Use REAL examples from the candidate's experience.

Candidate experience:{exp_text}
Question: {req.question}

Build a STAR answer:
- Situation: Set the scene with a real example
- Task: What was your specific responsibility
- Action: What YOU did (use "I", not "we")
- Result: Quantifiable outcome if possible

Keep total answer ~200 words. Be specific, not generic."""

    text = ai.generate_text(f"Build a STAR answer for: {req.question}", system, user_config)
    return {"answer": text}


class EvaluateAnswerRequest(BaseModel):
    question: str
    answer: str
    question_type: str = "behavioral"

@app.post("/api/interview/evaluate-answer")
async def evaluate_answer(req: EvaluateAnswerRequest, request: Request):
    user = get_user(request)
    user_config = db.get_config(user["id"])

    system = """Evaluate this interview answer. Return JSON only:
{
  "clarity": 1-5,
  "specificity": 1-5,
  "structure": 1-5,
  "relevance": 1-5,
  "overall": 0-100,
  "strengths": ["..."],
  "improvements": ["..."],
  "betterAnswer": "A stronger version of this answer in ~100 words"
}
Be honest and specific. Don't inflate scores."""

    prompt = f"""Question: {req.question}
Question type: {req.question_type}
Answer: {req.answer}

Evaluate this answer."""

    result = ai.ask_ai(prompt, system, user_config, max_tokens=1000, force_json=True)
    try:
        data = json.loads(result)
    except:
        data = {"clarity": 3, "specificity": 3, "structure": 3, "relevance": 3, "overall": 50,
                "strengths": [], "improvements": ["Could not evaluate"], "betterAnswer": ""}
    return data


# ============================================================
# Phase 8 — Analytics
# ============================================================

@app.get("/api/analytics/overview")
async def analytics_overview(request: Request):
    user = get_user(request)
    entries = db.get_entries(user["id"])

    if not entries:
        return {"total": 0, "applied": 0, "responseRate": 0, "avgDaysToResponse": 0,
                "byStatus": {}, "bySource": {}, "recentActivity": []}

    from datetime import datetime as dt, timedelta

    total = len(entries)
    by_status = {}
    by_source = {}
    responded = 0
    total_days_to_response = 0

    for e in entries:
        status = e.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        source = e.get("source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1

        # Check if responded (status changed from applied)
        history = e.get("statusHistory", [])
        if len(history) > 1:
            responded += 1
            try:
                applied_time = dt.fromisoformat(history[0]["timestamp"])
                response_time = dt.fromisoformat(history[1]["timestamp"])
                total_days_to_response += (response_time - applied_time).days
            except:
                pass

    response_rate = (responded / total * 100) if total > 0 else 0
    avg_days = (total_days_to_response / responded) if responded > 0 else 0

    # Recent activity (last 7 days)
    week_ago = (dt.now() - timedelta(days=7)).isoformat()
    recent = [e for e in entries if e.get("createdAt", "") >= week_ago]

    return {
        "total": total,
        "applied": by_status.get("applied", 0),
        "interviewing": by_status.get("interview", 0) + by_status.get("phone_screen", 0),
        "offers": by_status.get("offer", 0),
        "rejected": by_status.get("rejected", 0),
        "responseRate": round(response_rate, 1),
        "avgDaysToResponse": round(avg_days, 1),
        "byStatus": by_status,
        "bySource": by_source,
        "thisWeek": len(recent),
    }


# ============================================================
# Phase 6 — ATS Checker
# ============================================================

def _check_ats_internal(profile: dict, job_description: str = None) -> dict:
    """Internal ATS checker"""
    import re as _re

    ACTION_VERBS = [
        "achieved", "improved", "trained", "managed", "created", "resolved", "negotiated",
        "developed", "built", "designed", "led", "implemented", "optimized", "reduced",
        "increased", "automated", "delivered", "analyzed", "migrated", "integrated",
        "architected", "deployed", "monitored", "established", "improved", "streamlined",
        "engineered", "orchestrated", "spearheaded", "facilitated", "collaborated",
        "directed", "supervised", "mentored", "researched", "evaluated", "formulated",
        "initiated", "launched", "piloted", "transformed", "revitalized", "consolidated"
    ]

    issues = []
    score = 100

    # Check required sections
    if not profile.get("summary"):
        issues.append({"type": "missing_section", "severity": "high", "message": "No summary/objective section"})
        score -= 15

    if not profile.get("skills") or len(profile.get("skills", [])) < 3:
        issues.append({"type": "missing_section", "severity": "high", "message": "Need at least 3 skills listed"})
        score -= 10

    if not profile.get("experience"):
        issues.append({"type": "missing_section", "severity": "high", "message": "No work experience listed"})
        score -= 20

    if not profile.get("education"):
        issues.append({"type": "missing_section", "severity": "medium", "message": "No education section"})
        score -= 5

    # Check contact info
    if not profile.get("email"):
        issues.append({"type": "missing_info", "severity": "high", "message": "No email address"})
        score -= 10
    if not profile.get("phone"):
        issues.append({"type": "missing_info", "severity": "low", "message": "Consider adding phone number"})
        score -= 2

    # Check bullets
    for exp in profile.get("experience", []):
        for bullet in exp.get("highlights", []):
            first_word = bullet.split()[0].lower().rstrip(".,;:") if bullet.split() else ""
            if first_word not in ACTION_VERBS:
                issues.append({"type": "weak_bullet", "severity": "medium",
                    "message": f"Bullet should start with action verb: '{bullet[:60]}...'"})
                score -= 2

            if not _re.search(r'\d', bullet):
                issues.append({"type": "no_metric", "severity": "low",
                    "message": f"Consider adding metrics: '{bullet[:60]}...'"})
                score -= 1

    # Keyword matching against JD
    keywords_matched = []
    keywords_missing = []
    if job_description:
        tech_skills = [
            "python", "sql", "java", "javascript", "typescript", "react", "node", "angular", "vue",
            "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "jenkins", "ci/cd",
            "mongodb", "postgresql", "mysql", "redis", "elasticsearch", "kafka", "spark", "hadoop",
            "airflow", "dbt", "snowflake", "bigquery", "redshift", "tableau", "power bi", "excel",
            "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "machine learning", "deep learning",
            "nlp", "computer vision", "api", "rest", "graphql", "microservices", "agile", "scrum",
            "git", "linux", "bash", "fastapi", "django", "flask", "spring", "dotnet", "c++", "c#",
            "go", "rust", "scala", "r", "matlab", "sas", "etl", "data pipeline", "data warehouse",
            "data lake", "streaming", "batch processing", "real-time", "lambda", "s3", "ec2",
            "cloud", "serverless", "devops", "sre", "security", "networking", "tcp/ip"
        ]
        jd_lower = job_description.lower()
        cv_text = f"{profile.get('summary', '')} {' '.join(profile.get('skills', []))} {json.dumps(profile.get('experience', []))}".lower()

        for skill in tech_skills:
            if skill in jd_lower:
                if skill in cv_text:
                    keywords_matched.append(skill)
                else:
                    keywords_missing.append(skill)

        if keywords_missing:
            match_rate = len(keywords_matched) / (len(keywords_matched) + len(keywords_missing))
            if match_rate < 0.5:
                score -= 15
                issues.append({"type": "low_keyword_match", "severity": "high",
                    "message": f"Only {int(match_rate*100)}% of job keywords present in CV"})
            elif match_rate < 0.75:
                score -= 5
                issues.append({"type": "low_keyword_match", "severity": "medium",
                    "message": f"{int(match_rate*100)}% keyword match — consider adding: {', '.join(keywords_missing[:5])}"})

    return {
        "score": max(0, min(100, score)),
        "issues": sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]),
        "keywordsMatched": keywords_matched,
        "keywordsMissing": keywords_missing,
        "summary": {
            "high": len([i for i in issues if i["severity"] == "high"]),
            "medium": len([i for i in issues if i["severity"] == "medium"]),
            "low": len([i for i in issues if i["severity"] == "low"]),
        }
    }


class ATSRequest(BaseModel):
    job_description: str = ""

@app.post("/api/cv/check-ats")
async def check_ats(req: ATSRequest, request: Request):
    user = get_user(request)
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    result = _check_ats_internal(profile, req.job_description or None)
    return result


@app.post("/api/cv/export-text")
async def export_cv_text(request: Request):
    user = get_user(request)
    profile_doc = db.get_profile(user["id"])
    profile = {}
    if profile_doc:
        p = profile_doc.get("profile_json", "{}")
        profile = json.loads(p) if isinstance(p, str) else p

    # Build plain text CV
    lines = []
    lines.append(profile.get("name", "Name").upper())
    lines.append(profile.get("title", ""))
    contact = []
    if profile.get("email"): contact.append(profile["email"])
    if profile.get("phone"): contact.append(profile["phone"])
    if profile.get("location"): contact.append(profile["location"])
    if contact: lines.append(" | ".join(contact))
    lines.append("")

    if profile.get("summary"):
        lines.append("SUMMARY")
        lines.append("-" * 40)
        lines.append(profile["summary"])
        lines.append("")

    if profile.get("skills"):
        lines.append("SKILLS")
        lines.append("-" * 40)
        lines.append(", ".join(profile["skills"]))
        lines.append("")

    for exp in profile.get("experience", []):
        lines.append(f"{exp.get('role', '')} — {exp.get('company', '')}")
        if exp.get("location"): lines.append(exp["location"])
        dates = f"{exp.get('startDate', '')} — {exp.get('endDate', 'Present')}"
        lines.append(dates)
        for h in exp.get("highlights", []):
            lines.append(f"  • {h}")
        lines.append("")

    for edu in profile.get("education", []):
        lines.append(f"{edu.get('degree', '')} in {edu.get('field', '')}")
        lines.append(f"{edu.get('institution', '')} ({edu.get('startYear', '')}–{edu.get('endYear', 'Present')})")
        lines.append("")

    return {"text": "\n".join(lines)}


# ============================================================
# Health
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3002)
