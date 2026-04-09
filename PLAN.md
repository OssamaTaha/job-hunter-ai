# Job Hunter AI — Full Agent Build Plan

> **Status:** In Progress
> **Started:** April 9, 2026
> **Current Phase:** Phase 1 — Foundation cleanup

---

## Phase 1 — Foundation cleanup
**Goal:** Get a single working app from the two existing repos. No new features yet.

### 1.1 Consolidate repositories
- [x] ~~Clone job-hunter-ai as backend-src~~
- [x] ~~Clone job-hunter as frontend-src~~
- [x] ~~Copy backend-src/ → job-hunter/backend/~~
- [x] ~~Copy frontend-src/ → job-hunter/ (root is Next.js)~~
- [ ] Delete duplicate .js API files where .ts version exists
- [ ] Remove main.py from root (use backend/app/main.py)

### 1.2 Environment setup
- [ ] Create .env.local.example with all required vars
- [ ] Document each env var

### 1.3 Fix known bugs
- [ ] `userId is required` in /api/claude — extract from JWT cookie
- [x] ~~`Mailbox doesn't exist: Sent` — try/catch per folder~~ ✅ Already handled in mail.py
- [x] ~~Demo mode bypasses all auth — remove hardcoded demo user~~ ✅ Fixed
- [ ] `job_id: undefined` in tracker — validate before DB write
- [x] ~~Scraper timeout returns fake jobs~~ ✅ Fixed — returns empty array
- [ ] Hardcoded secrets in start_prod.sh — load from .env only

### 1.4 Unified MongoDB connection
- [ ] lib/db.ts with proper connection pooling
- [ ] Ensure indexes on all collections

**Acceptance criteria:**
- [ ] `npm run dev` starts without errors
- [ ] `python -m uvicorn backend.app.main:app` starts without errors
- [ ] Login, signup, logout work
- [ ] No hardcoded secrets anywhere
- [ ] All known bugs from 1.3 fixed

---

## Phase 2 — User profile system
**Goal:** Rich structured profile that every other feature draws from.

### 2.1 Profile data model
- [ ] types/index.ts — UserProfile, WorkExperience, Project, Education, Language
- [ ] Job preferences section

### 2.2 Profile API
- [ ] GET /api/profile
- [ ] POST /api/profile (partial update via merge)
- [ ] POST /api/profile/parse-yaml
- [ ] POST /api/profile/import-linkedin (future)

### 2.3 Profile tab UI
- [ ] Basic info section
- [ ] Job preferences section
- [ ] Skills tag input
- [ ] Experience entries CRUD
- [ ] Education & certifications
- [ ] Languages
- [ ] AI fill from CV button per section

### 2.4 YAML CV parser
- [ ] Extend to extract preferences fields
- [ ] Extract target_roles, salary_expectation, notice_period

**Acceptance criteria:**
- [ ] Profile CRUD works end-to-end
- [ ] YAML import populates all fields
- [ ] Preferences section saves/retrieves correctly
- [ ] Profile completeness score (0-100%)

---

## Phase 3 — Job search & fit scoring
**Goal:** Multi-source job search with per-job fit scores.

### 3.1 Scraper architecture
- [x] ~~Unified entry point~~ ✅ claw-job-search.js with deep web search
- [x] ~~Never return fake jobs~~ ✅ Returns empty on failure
- [x] ~~30-min MongoDB cache~~ ✅ Implemented
- [x] ~~Required fields on every job~~ ✅ id, title, company, location, remote, description, applyUrl, source

### 3.2 Free API integrations
- [ ] Remotive API
- [ ] Arbeitnow API
- [ ] Jobicy API

### 3.3 Fit score engine
- [ ] lib/fit-score.ts (frontend)
- [ ] backend/app/services/fit_score.py (backend)
- [ ] Title match (fuzzy + synonyms)
- [ ] Skill overlap calculation
- [ ] Location match
- [ ] Seniority match
- [ ] Salary match
- [ ] FitScoreBar component

### 3.4 Search API
- [ ] POST /api/search with cache, scoring, pagination

### 3.5 Skills gap detection
- [ ] POST /api/search/skills-gap endpoint

**Acceptance criteria:**
- [ ] Search returns real jobs from 2+ sources ✅
- [ ] Empty results (not fake) when all sources fail ✅
- [ ] Fit score on every job card
- [ ] Best match sort works
- [ ] 30-min cache works ✅

---

## Phase 4 — Application tracker
**Goal:** Track every application — from app, email, or manual entry.

### 4.1 Entry data model
- [ ] TrackerEntry type definition
- [ ] Status pipeline: saved → applied → phone_screen → interview → offer → rejected/withdrawn
- [ ] Status history tracking

### 4.2 Kanban board
- [ ] KanbanBoard component with @dnd-kit
- [ ] 7 columns: Saved, Applied, Phone Screen, Interview, Offer, Rejected, Withdrawn
- [ ] Card: company logo, title, date, source badge, fit score
- [ ] Drag-and-drop saves status history

### 4.3 Manual job card modal
- [ ] ManualJobModal with all fields
- [ ] Channel selector: portal/email/phone/WhatsApp/referral/LinkedIn
- [ ] Follow-up reminder date

### 4.4 Email → tracker sync
- [ ] mail_classifier.py — classify email types
- [ ] Match emails to tracker entries
- [ ] Auto-update status on match
- [ ] Create entry with needsReview for unmatched job emails
- [ ] POST /api/mail/sync endpoint

### 4.5 Tracker API
- [ ] GET /api/jobs — all entries
- [ ] POST /api/jobs — create entry
- [ ] PUT /api/jobs/:id — update
- [ ] DELETE /api/jobs/:id — remove
- [ ] GET /api/jobs/:id/emails — linked emails

**Acceptance criteria:**
- [ ] Kanban renders all entries in correct columns
- [ ] Drag-and-drop saves status history
- [ ] Manual card creates entry for all channel types
- [ ] Email sync detects applied/rejection emails

---

## Phase 5 — AI generation tools
**Goal:** Cover letters, Q&A answers, CV tailoring — grounded in profile + job.

### 5.1 Unified AI client
- [ ] AIClient class — Groq primary, OpenRouter fallback
- [ ] Never expose API keys in responses

### 5.2 Cover letter generator
- [ ] POST /api/generate/cover-letter
- [ ] Tone selector: formal/friendly/direct
- [ ] Length selector: short/standard/detailed
- [ ] Uses real profile data, no placeholders

### 5.3 Application Q&A answer generator
- [ ] POST /api/generate/qa-answer
- [ ] Common questions mapped to prompt variants

### 5.4 CV tailoring per job
- [ ] POST /api/generate/tailor-cv
- [ ] Keyword extraction from JD
- [ ] Bullet rewrite suggestions

### 5.5 Follow-up email generator
- [ ] POST /api/generate/follow-up
- [ ] Auto-reminder 10 days after applied

### 5.6 Frontend modals
- [ ] CoverLetterModal
- [ ] GenerateAnswerModal

**Acceptance criteria:**
- [ ] Cover letter uses real profile data
- [ ] Q&A uses real experience
- [ ] CV tailoring returns specific suggestions

---

## Phase 6 — ATS CV builder
**Goal:** Build, edit, score, and export professional CVs that pass ATS.

### 6.1 ATS checker
- [ ] check_ats() — format checks, keyword density
- [ ] Action verb validation (200+ list)
- [ ] Metric presence detection

### 6.2 CV editor
- [ ] Monaco editor (YAML mode) + live preview
- [ ] Real-time ATS score updates
- [ ] Click issue → jump to line
- [ ] "AI fix" button per issue

### 6.3 CV export
- [ ] PDF via RenderCV
- [ ] DOCX via python-docx
- [ ] Plain text export

**Acceptance criteria:**
- [ ] ATS score updates in real time
- [ ] High-severity issues are actionable
- [ ] PDF export is professional

---

## Phase 7 — Interview preparation
**Goal:** Role-specific, profile-grounded interview prep.

### 7.1 Question bank
- [ ] AI-generated per role + level
- [ ] Cached 7 days in MongoDB
- [ ] Types: behavioral, technical, situational, company

### 7.2 STAR answer builder
- [ ] POST /api/interview/star-answer
- [ ] Uses profile experience entries

### 7.3 Mock interview mode
- [ ] Questions one at a time
- [ ] Score each answer: clarity, specificity, STAR, relevance
- [ ] Overall score + improvement areas

### 7.4 Company research
- [ ] Web search for company culture + news
- [ ] Questions to ask interviewer

### 7.5 Technical question sets
- [ ] Pre-built by role: Data Engineer, Analyst, SWE, DevOps, PM

**Acceptance criteria:**
- [ ] Questions are role-specific
- [ ] STAR uses real profile content
- [ ] Evaluation is actionable

---

## Phase 8 — Analytics & intelligence
**Goal:** Surface patterns from job search activity.

### 8.1 Application analytics
- [ ] Total applied (week/month)
- [ ] Response rate
- [ ] Average time to response
- [ ] Top rejection stage
- [ ] Source performance
- [ ] Application velocity chart

### 8.2 Salary intelligence
- [ ] Aggregate from cached jobs with salary mentions
- [ ] Negotiation tips

### 8.3 Weekly digest (optional)
- [ ] HTML email content with weekly summary

### 8.4 Skills market analysis
- [ ] Top skills by frequency
- [ ] Rising/declining trends
- [ ] User's match percentage

**Acceptance criteria:**
- [ ] Response rate calculation correct
- [ ] Charts render in light/dark themes

---

## Phase 9 — Chat agent (unified interface)
**Goal:** All features accessible through single chat.

### 9.1 Intent classification
- [ ] 8 intents: job_search, cover_letter, interview_prep, cv_review, application_answer, tracker_add, salary_info, general

### 9.2 Chat response format
- [ ] ChatResponse with text, intent, jobs, coverLetter, interviewQuestions, atsIssues, actions

### 9.3 Chat memory
- [ ] Last 10 messages in session
- [ ] Cross-session summary in profile

### 9.4 Quick action buttons
- [ ] Contextual actions after each response

**Acceptance criteria:**
- [ ] Intent classification for all 8 types
- [ ] Job search returns real jobs with fit scores
- [ ] Fallback to general chat works

---

## Decisions already made (do not revisit)

| Decision | Rationale |
|----------|-----------|
| MongoDB (not SQLite) | Flexible schema for evolving profile + tracker data |
| Groq (not OpenAI) | Free tier sufficient, fast inference |
| Playwright + Firecrawl | Job boards have no public API |
| Free APIs as fallback | Remotive/Arbeitnow/Jobicy stable and free |
| YAML CV (RenderCV) | Portable, version-controllable, professional PDF |
| Next.js + FastAPI | Next.js for UI/auth; Python for AI, scraping, IMAP |
| JWT HTTP-only cookie | XSS-safe auth |
| No auto-apply | Legal/ethical complexity; out of scope v1 |

---

*Last updated: April 9, 2026*
