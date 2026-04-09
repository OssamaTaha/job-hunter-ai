from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import subprocess
import json
import os
import re
import asyncio
from datetime import datetime

from lib import db, ai, auth, crypto, mail, profile_parser

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

@app.get("/api/profile")
async def get_profile(request: Request):
    user = get_user(request)
    doc = db.get_profile(user["id"])
    if not doc:
        return {"profile": {}, "cvYaml": ""}
    profile = doc.get("profile_json", "{}")
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except Exception:
            profile = {}
    return {"profile": profile, "cvYaml": doc.get("cv_yaml", "")}

@app.post("/api/profile")
async def save_profile(req: ProfileRequest, request: Request):
    user = get_user(request)
    profile = req.profile or {}
    cv_yaml = req.cv_yaml or ""
    if cv_yaml and not profile:
        profile = profile_parser.parse_cv_yaml(cv_yaml)
    db.save_profile(user["id"], profile, cv_yaml)
    return {"ok": True, "profile": profile}

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


def _score_jobs(jobs: List[Job], skills: list) -> List[Job]:
    if not skills:
        return jobs
    skills_lower = [s.lower() for s in skills]
    for job in jobs:
        score = 0
        title_lower = job.title.lower()
        desc_lower = (job.description or "").lower()
        for skill in skills_lower:
            if skill in title_lower:
                score += 30
            elif skill in desc_lower:
                score += 15
        job.fit_score = min(score, 100)
    jobs.sort(key=lambda j: j.fit_score or 0, reverse=True)
    return jobs


def search_with_claude(query: str, location: str, limit: int = 10) -> List[Job]:
    """
    Search for jobs using our custom scraper that gets REAL individual job postings
    from Wuzzuf, Indeed, and other sites - NOT aggregator pages.
    """
    import subprocess
    import json
    import os
    
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
            return []  # No fake results — return empty
        
        # Parse the JSON output
        data = json.loads(result.stdout)
        jobs_data = data.get("jobs", [])
        
        if not jobs_data:
            return []  # No fake results — return empty
        
        # Convert to Job objects and filter for REAL individual jobs (not aggregator pages)
        jobs = []
        seen_urls = set()
        
        for job_data in jobs_data:
            # Skip if we've seen this URL already
            apply_url = job_data.get("applyUrl", "")
            if apply_url in seen_urls or not apply_url or apply_url == "#":
                continue
            seen_urls.add(apply_url)
            
            # Filter out aggregator/search pages - look for signs of individual job postings
            title = job_data.get("title", "").lower()
            company = job_data.get("company", "").lower()
            source = job_data.get("source", "").lower()
            
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
                jobs.append(Job(
                    id=job_data.get("id", f"job-{len(jobs)}"),
                    title=job_data.get("title", "Unknown Position")[:200],
                    company=job_data.get("company", "Unknown Company")[:100],
                    location=job_data.get("location", location)[:100],
                    remote=job_data.get("remote", False),
                    description=job_data.get("description", "")[:500],
                    apply_url=job_data.get("applyUrl", "#"),
                    url=job_data.get("applyUrl", "#"),  # For backward compatibility
                    source=job_data.get("source", "Job Board"),
                    posted=job_data.get("posted"),
                    fit_score=None
                ))
                
                # Stop when we have enough real jobs
                if len(jobs) >= limit:
                    break
        
        # If we got real jobs, return them
        if jobs:
            return jobs
        
        # If no real jobs found from scraping, try a different approach
        # Let's try to get some basic info even if filtered out
        fallback_jobs = []
        for job_data in jobs_data[:limit]:
            apply_url = job_data.get("applyUrl", "")
            if apply_url and apply_url not in seen_urls and apply_url != "#":
                seen_urls.add(apply_url)
                fallback_jobs.append(Job(
                    id=job_data.get("id", f"job-{len(fallback_jobs)}"),
                    title=job_data.get("title", f"{query} Position")[:200],
                    company=job_data.get("company", "Company")[:100] if job_data.get("company", "").lower() not in ['apply via link', 'unknown', ''] else "Company",
                    location=job_data.get("location", location)[:100],
                    remote=job_data.get("remote", False),
                    description=job_data.get("description", f"{query} position")[:500],
                    apply_url=job_data.get("applyUrl", "#"),
                    url=job_data.get("applyUrl", "#"),
                    source=job_data.get("source", "Job Board"),
                    posted=job_data.get("posted"),
                    fit_score=None
                ))
        
        return fallback_jobs if fallback_jobs else []
        
    except subprocess.TimeoutExpired:
        print("[SCRAPER ERROR] Timeout scraping jobs")
    except json.JSONDecodeError as e:
        print(f"[SCRAPER ERROR] Invalid JSON from scraper: {e}")
    except Exception as e:
        print(f"[SCRAPER ERROR] {e}")
    
    # No fake results
    return []


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
                jobs = _score_jobs(jobs, p.get("skills", []))
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
            jobs = _score_jobs(jobs, p.get("skills", []))

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
async def update_job(req: EntryUpdate, request: Request):
    user = get_user(request)
    data = {}
    if req.status:
        data["status"] = req.status
    if req.data:
        data["data_json"] = req.data
    db.update_entry(user["id"], req.job_id, data)
    return {"ok": True}

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    user = get_user(request)
    db.delete_entry(user["id"], job_id)
    return {"ok": True}


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
    # Demo mode: use demo user
    user = {"id": "demo", "username": "demo"}
    
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
        if any(w in greeting_stripped for w in ['interview', 'prep', 'practice', 'mock']):
            intent = "interview_prep"
        elif any(w in greeting_stripped for w in ['cv', 'resume', 'review', 'feedback']):
            intent = "cv_review"
    
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
        response_text = await ai.cv_review(user_message, profile, user_config)
    
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
# Health
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3002)
