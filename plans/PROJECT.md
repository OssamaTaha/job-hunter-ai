# Job Hunter AI - Project Plan

## Vision
Build an AI agent that helps you land jobs - from CV creation to interview prep.

**Reference:** career-ops (github.com/santifer/career-ops) - make it better

---

## Phase 1: Working Chat (Priority)
**Goal:** Make the chat actually reply with AI

- [ ] 1.1 Get Groq API key (free tier works)
- [ ] 1.2 Fix the lib/ai.py to not require key in env
- [ ] 1.3 Test simple chat reply
- [ ] 1.4 Remove broken Hermes search dependency

**Status:** TODO

---

## Phase 2: CV Builder
**Goal:** Collect user info and create CV

- [ ] 2.1 Create CV wizard - chat-based questions
- [ ] 2.2 Collect: name, summary, experience, skills, education
- [ ] 2.3 Generate markdown CV
- [ ] 2.4 Store in MongoDB
- [ ] 2.5 Export to PDF

**Status:** TODO

---

## Phase 3: Job Search Agent
**Goal:** Find and validate jobs against CV

- [ ] 3.1 Web search for jobs (DuckDuckGo)
- [ ] 3.2 Extract job details (title, company, location, URL)
- [ ] 3.3 Match jobs to CV skills
- [ ] 3.4 Score and rank matches
- [ ] 3.5 Validate jobs still exist

**Status:** TODO

---

## Phase 4: Application Helper
**Goal:** Help apply to jobs

- [ ] 4.1 Generate tailored cover letter
- [ ] 4.2 Track applications in DB
- [ ] 4.3 Follow-up reminders
- [ ] 4.4 Response tracking

**Status:** TODO

---

## Phase 5: Interview Prep
**Goal:** Prepare for interviews

- [ ] 5.1 Generate common questions
- [ ] 5.2 STAR method answers
- [ ] 5.3 Mock interview mode
- [ ] 5.4 Feedback on answers

**Status:** TODO

---

## Tech Stack
- FastAPI (Python)
- MongoDB (data)
- Groq/OpenRouter (LLM)
- DuckDuckGo (search)

---

## Progress Log

### 2026-04-08
- Created this plan
- Started Phase 1: Getting chat to work