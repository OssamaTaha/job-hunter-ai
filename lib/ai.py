import os
import json
import time
import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"
FAST_MODEL = "groq/llama-3.1-8b-instant"
OPENROUTER_MODEL = "meta-llama/llama-3.1-8b-instruct"


def _get_api_key(user_config: dict = None, provider: str = "groq") -> str:
    if user_config:
        if provider == "groq" and user_config.get("GROQ_API_KEY"):
            from lib.crypto import decrypt
            try:
                return decrypt(user_config["GROQ_API_KEY"])
            except:
                return user_config.get("GROQ_API_KEY", "")
        elif provider == "openrouter" and user_config.get("OPENROUTER_API_KEY"):
            from lib.crypto import decrypt
            try:
                return decrypt(user_config["OPENROUTER_API_KEY"])
            except:
                return user_config.get("OPENROUTER_API_KEY", "")
    
    # Check environment
    if provider == "groq":
        return os.environ.get("GROQ_API_KEY", "")
    return os.environ.get("OPENROUTER_API_KEY", "")


def ask_ai(prompt: str, system: str = "", user_config: dict = None, model: str = None,
           max_tokens: int = 1000, force_json: bool = True) -> str:
    
    # Try Groq first
    api_key = _get_api_key(user_config, "groq")
    
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if not model:
        model = DEFAULT_MODEL

    # Try Groq
    if api_key:
        try:
            resp = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model.replace("groq/", ""), "messages": messages, "max_tokens": max_tokens},
                timeout=25.0
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Groq error: {e}")

    # Try OpenRouter as fallback
    or_key = _get_api_key(user_config, "openrouter")
    if or_key:
        try:
            resp = httpx.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json", "HTTP-Referer": "https://jobhunter.tahalabs.dpdns.org", "X-Title": "JobHunter"},
                json={"model": OPENROUTER_MODEL, "messages": messages, "max_tokens": max_tokens},
                timeout=25.0
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"OpenRouter error: {e}")
    
    # No API key - return empty to trigger fallback response
    return ""


def classify_email_ai(subject: str, body_snippet: str, user_config: dict = None) -> dict:
    system = """You classify job-related emails. Return JSON:
{"category":"applied|interview|offer|rejected|shortlisted|general","summary":"one line","action_items":[],"sentiment":"positive|negative|neutral","isJob":true/false}"""

    prompt = f"Subject: {subject}\n\nBody: {body_snippet[:500]}"
    result = ask_ai(prompt, system, user_config, max_tokens=300)

    try:
        return json.loads(result)
    except Exception:
        # Fallback heuristics
        subj_lower = subject.lower()
        if any(w in subj_lower for w in ["interview", "schedule", "meeting"]):
            return {"category": "interview", "summary": subject, "action_items": [], "sentiment": "positive", "isJob": True}
        if any(w in subj_lower for w in ["offer", "congratulations", "welcome"]):
            return {"category": "offer", "summary": subject, "action_items": [], "sentiment": "positive", "isJob": True}
        if any(w in subj_lower for w in ["unfortunately", "regret", "not selected", "rejected"]):
            return {"category": "rejected", "summary": subject, "action_items": [], "sentiment": "negative", "isJob": True}
        if any(w in subj_lower for w in ["application", "applied", "received", "thank you for applying"]):
            return {"category": "applied", "summary": subject, "action_items": [], "sentiment": "neutral", "isJob": True}
        return {"category": "general", "summary": subject, "action_items": [], "sentiment": "neutral", "isJob": False}


def discover_job_ai(subject: str, body_snippet: str, from_str: str, user_config: dict = None) -> dict:
    # Skip job board notification emails
    board_domains = ["indeed", "linkedin", "bayt", "glassdoor", "wuzzuf", "naukri"]
    from_lower = from_str.lower()
    if any(b in from_lower for b in board_domains):
        return {"isJob": False, "company": "", "role": "", "status": "general", "confidence": 0}

    system = """Extract job info from email. Return JSON:
{"isJob":true/false,"company":"","role":"","status":"applied|interview|offer|rejected","confidence":0.0-1.0}"""

    prompt = f"From: {from_str}\nSubject: {subject}\n\nBody: {body_snippet[:500]}"
    result = ask_ai(prompt, system, user_config, max_tokens=200)

    try:
        data = json.loads(result)
        if data.get("confidence", 0) < 0.8:
            data["isJob"] = False
        return data
    except Exception:
        return {"isJob": False, "company": "", "role": "", "status": "general", "confidence": 0}


def chat_with_context(messages: list, profile: dict = None, job_context: dict = None,
                      user_config: dict = None) -> str:
    """
    Enhanced career coach with specific job-hunting capabilities:
    - Job analysis vs CV
    - Cover letter generation
    - Interview preparation
    - CV improvement suggestions
    - Career path advice
    """
    system_parts = ["You are Claw, an expert career coach and job search assistant. You're helpful, direct, and practical. "
    
    "You help users with: "
    "1. Job Search - Find relevant jobs, analyze fit "
    "2. CV Analysis - Compare CV to job requirements, suggest improvements "
    "3. Cover Letters - Generate tailored cover letters "
    "4. Interview Prep - Common questions, STAR method answers, role-specific prep "
    "5. Career Advice - Salary negotiation, career transitions, skill gaps "
    
    "IMPORTANT: Be practical and actionable. Don't just give advice - help them DO it. "
    "When generating cover letters or emails, write them ready to send. "
    "When suggesting CV improvements, be specific about what to add/remove."]

    if profile:
        system_parts.append(f"\nCandidate Profile:")
        if profile.get("name"):
            system_parts.append(f"Name: {profile['name']}")
        if profile.get("title"):
            system_parts.append(f"Title: {profile['title']}")
        if profile.get("summary"):
            system_parts.append(f"Summary: {profile['summary']}")
        if profile.get("skills"):
            system_parts.append(f"Skills: {', '.join(profile['skills'][:30])}")
        if profile.get("experience"):
            system_parts.append("Experience:")
            for exp in profile["experience"][:5]:
                system_parts.append(f"  - {exp.get('role', '')} at {exp.get('company', '')} ({exp.get('startDate', '')}-{exp.get('endDate', '')})")
                for h in (exp.get("highlights", []) or [])[:3]:
                    system_parts.append(f"    * {h}")
        if profile.get("projects"):
            system_parts.append("Projects:")
            for p in profile["projects"][:5]:
                system_parts.append(f"  - {p.get('name', '')}: {p.get('desc', '')}")
        if profile.get("education"):
            system_parts.append(f"Education: {profile['education']}")

    if job_context:
        system_parts.append(f"\nTarget Job:")
        system_parts.append(f"Title: {job_context.get('title', '')}")
        system_parts.append(f"Company: {job_context.get('company', '')}")
        if job_context.get("description"):
            system_parts.append(f"Description: {job_context['description'][:500]}")

    system = "\n".join(system_parts)
    api_key = _get_groq_key(user_config)
    if not api_key:
        return "Please configure your Groq API key in Settings."

    all_messages = [{"role": "system", "content": system}] + messages

    try:
        resp = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": FAST_MODEL, "messages": all_messages, "max_tokens": 800, "temperature": 0.7},
            timeout=20.0
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI error: {str(e)}"


def generate_text(prompt: str, system: str = "", user_config: dict = None) -> str:
    return ask_ai(prompt, system, user_config, force_json=False, max_tokens=1500)


# ============================================================
# New async AI functions for unified chat
# ============================================================

async def interview_prep(user_message: str, profile: dict, user_config: dict) -> str:
    """Handle interview prep requests"""
    system = """You are Job Hunter, an expert interview prep assistant. You help users prepare for job interviews.

Be practical and give specific, actionable advice. Include:
- Common interview questions with suggested answers
- STAR method examples for behavioral questions
- Technical questions if applicable to their field
- Tips for the specific role/company if mentioned

Use a confident, encouraging tone. Keep it concise but comprehensive."""

    if profile:
        user_context = f"\nUser's background: {profile.get('title', 'N/A')}, Skills: {', '.join(profile.get('skills', [])[:15])}"
    else:
        user_context = ""

    prompt = f"{user_message}{user_context}\n\nProvide practical interview preparation advice."
    
    return generate_text(prompt, system, user_config)


async def cv_review(user_message: str, profile: dict, user_config: dict) -> str:
    """Handle CV review requests"""
    system = """You are Job Hunter, an expert CV/resume reviewer. You give practical feedback on CVs to help users get more interviews.

Be specific about:
- What's working well
- What to improve or remove
- Keywords to add for ATS
- Format/structure suggestions
- Action verbs to use

Keep feedback actionable and prioritize the most important changes."""

    if profile:
        cv_text = f"\nUser's CV:\n{json.dumps(profile, indent=2)}"
    else:
        cv_text = ""

    prompt = f"Review this CV and provide feedback:{cv_text}\n\nUser said: {user_message}"
    
    return generate_text(prompt, system, user_config)


async def chat_general(user_message: str, profile: dict, user_config: dict, history: list) -> str:
    """Handle general career advice"""
    system = """You are Job Hunter, a helpful and edgy job hunting assistant. 

Your personality:
- Direct and practical, not overly formal
- Tech-savvy, internet kid vibes
- Encouraging but honest
- Use some slang naturally

You help with:
- General career advice
- Job market insights
- Salary negotiation tips
- Networking advice
- Any other job search questions

Keep responses conversational and helpful. Use emojis occasionally."""

    if profile:
        user_context = f"\nContext: {profile.get('name', '')} - {profile.get('title', '')}. Skills: {', '.join(profile.get('skills', [])[:10])}"
    else:
        user_context = ""

    # Build conversation history
    messages = []
    if history:
        for msg in history[-5:]:  # Last 5 messages
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    # Try both providers
    api_key = _get_api_key(user_config, "groq") or _get_api_key(user_config, "openrouter")
    if not api_key:
        # Demo fallback - just acknowledge and ask what they need
        msg_lower = user_message.lower()
        if any(w in msg_lower for w in ['find', 'search', 'jobs', 'work']):
            return "I can help you find jobs! Just click the quick search buttons or tell me what you're looking for. For example: 'find python developer jobs in Cairo'"
        elif any(w in msg_lower for w in ['cv', 'resume', 'profile']):
            return "I can help you build a CV! Go to Settings and fill in your profile info, or just tell me about your experience and skills and I'll help you create one."
        elif any(w in msg_lower for w in ['interview', 'prep']):
            return "Let's prep for interviews! Tell me about the role you're interviewing for and I'll generate some practice questions."
        else:
            return "Hey! I'm Job Hunter 🤖 I help you find jobs, build CVs, and prep for interviews. What do you need?"

    try:
        system_msg = {"role": "system", "content": system + user_context}
        all_msgs = [system_msg] + messages
        
        import httpx
        
        # Try Groq first
        if _get_api_key(user_config, "groq"):
            api_key = _get_api_key(user_config, "groq")
            resp = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "llama-3.1-8b-instant", "messages": all_msgs, "max_tokens": 600, "temperature": 0.7},
                timeout=20.0
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        
        # Try OpenRouter
        if _get_api_key(user_config, "openrouter"):
            api_key = _get_api_key(user_config, "openrouter")
            resp = httpx.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://jobhunter.tahalabs.dpdns.org", "X-Title": "JobHunter"},
                json={"model": OPENROUTER_MODEL, "messages": all_msgs, "max_tokens": 600, "temperature": 0.7},
                timeout=20.0
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        
        return "I'm having trouble connecting to the AI right now. Try again in a moment!"
    except Exception as e:
        return f"Hey, something broke on my end 🔧 Try again?"
