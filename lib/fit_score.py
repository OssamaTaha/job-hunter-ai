"""
Fit Score Engine for Job Matching
Scores jobs 0-100 based on profile match
"""

import re
import difflib
from typing import Dict, List, Optional, Tuple

# Predefined list of 200+ skills/technologies for keyword extraction
TECH_SKILLS = [
    # Programming Languages
    'python', 'javascript', 'typescript', 'java', 'c++', 'c#', 'go', 'golang',
    'rust', 'ruby', 'php', 'swift', 'kotlin', 'scala', 'r', 'perl', 'lua',
    'dart', 'elixir', 'haskell', 'clojure', 'erlang', 'f#', 'objective-c',
    'vba', 'matlab', 'groovy', 'assembly', 'cobol', 'fortran', 'pascal',
    
    # Web Frontend
    'react', 'react.js', 'reactjs', 'vue', 'vue.js', 'vuejs', 'angular', 'angularjs',
    'svelte', 'next.js', 'nextjs', 'nuxt.js', 'nuxtjs', 'gatsby', 'remix',
    'html', 'html5', 'css', 'css3', 'sass', 'scss', 'less', 'tailwind',
    'tailwindcss', 'bootstrap', 'material-ui', 'mui', 'chakra-ui', 'styled-components',
    'webpack', 'vite', 'babel', 'jquery', 'redux', 'mobx', 'zustand', 'recoil',
    
    # Web Backend
    'node.js', 'nodejs', 'express', 'express.js', 'nestjs', 'fastify', 'koa',
    'django', 'flask', 'fastapi', 'spring', 'spring boot', 'springboot',
    'rails', 'ruby on rails', 'laravel', 'symfony', 'codeigniter',
    'asp.net', 'aspnet', '.net', 'dotnet', 'blazor',
    'gin', 'fiber', 'echo', 'actix', 'rocket',
    
    # Databases
    'sql', 'nosql', 'mysql', 'postgresql', 'postgres', 'mongodb', 'redis',
    'elasticsearch', 'elastic', 'sqlite', 'oracle', 'sql server', 'sqlserver',
    'mariadb', 'dynamodb', 'cassandra', 'couchdb', 'neo4j', 'firebase',
    'supabase', 'planetscale', 'prisma', 'sequelize', 'typeorm', 'mongoose',
    'knex', 'drizzle',
    
    # Cloud & DevOps
    'aws', 'amazon web services', 'azure', 'gcp', 'google cloud', 'google cloud platform',
    'docker', 'kubernetes', 'k8s', 'terraform', 'ansible', 'puppet', 'chef',
    'jenkins', 'gitlab ci', 'github actions', 'circleci', 'travis ci', 'argo',
    'helm', 'prometheus', 'grafana', 'datadog', 'new relic', 'splunk',
    'nginx', 'apache', 'caddy', 'cloudflare', 'vercel', 'netlify', 'heroku',
    'digitalocean', 'linode', 'vultr', 'ec2', 's3', 'lambda', 'ecs', 'eks',
    
    # Data & ML
    'machine learning', 'ml', 'deep learning', 'dl', 'ai', 'artificial intelligence',
    'tensorflow', 'pytorch', 'keras', 'scikit-learn', 'sklearn', 'pandas',
    'numpy', 'scipy', 'matplotlib', 'seaborn', 'plotly', 'jupyter',
    'data science', 'data engineering', 'data analysis', 'data analytics',
    'etl', 'elt', 'airflow', 'dagster', 'prefect', 'luigi', 'spark',
    'apache spark', 'pyspark', 'hadoop', 'hive', 'kafka', 'flink',
    'nlp', 'natural language processing', 'computer vision', 'cv',
    'opencv', 'transformers', 'huggingface', 'bert', 'gpt', 'llm',
    'large language model', 'langchain', 'openai', 'anthropic',
    
    # Mobile
    'ios', 'android', 'react native', 'reactnative', 'flutter', 'xamarin',
    'ionic', 'cordova', 'capacitor', 'swiftui', 'jetpack compose',
    
    # Tools & Platforms
    'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence',
    'slack', 'notion', 'trello', 'asana', 'monday.com',
    'figma', 'sketch', 'adobe xd', 'photoshop', 'illustrator',
    'postman', 'insomnia', 'swagger', 'openapi', 'graphql', 'grpc',
    'rest', 'restful', 'api', 'microservices', 'serverless',
    
    # Testing
    'jest', 'mocha', 'chai', 'cypress', 'playwright', 'selenium',
    'pytest', 'unittest', 'junit', 'testng', 'rspec', 'phpunit',
    'testing', 'tdd', 'bdd', 'unit test', 'integration test', 'e2e',
    
    # Security
    'security', 'cybersecurity', 'penetration testing', 'pentest',
    'owasp', 'oauth', 'jwt', 'saml', 'ldap', 'ssl', 'tls', 'https',
    
    # Soft Skills / Roles
    'agile', 'scrum', 'kanban', 'waterfall', 'project management',
    'team lead', 'tech lead', 'architect', 'devops', 'sre',
    'full stack', 'fullstack', 'frontend', 'backend', 'front-end', 'back-end',
    'mobile', 'web', 'desktop', 'embedded', 'iot',
    
    # Other
    'linux', 'unix', 'windows', 'macos', 'bash', 'shell', 'powershell',
    'vim', 'vscode', 'visual studio code', 'intellij', 'pycharm',
    'oop', 'object oriented', 'functional programming', 'fp',
    'design patterns', 'solid', 'clean code', 'clean architecture',
    'ci/cd', 'cicd', 'continuous integration', 'continuous deployment',
]

# Seniority level indicators
SENIORITY_LEVELS = {
    'junior': ['junior', 'jr', 'entry', 'entry-level', 'graduate', 'intern', 'internship', 'trainee', 'associate', '0-2 years', '1+ years'],
    'mid': ['mid', 'mid-level', 'intermediate', 'regular', 'standard', '2-5 years', '3+ years', '3-5 years'],
    'senior': ['senior', 'sr', 'lead', 'principal', 'staff', '5+ years', '5-10 years', '7+ years', '8+ years'],
    'manager': ['manager', 'director', 'head', 'vp', 'vice president', 'chief', 'cto', 'cio', 'cpo', '10+ years', '15+ years'],
}

# Experience level mapping to years
EXPERIENCE_YEARS = {
    'junior': 1,
    'mid': 4,
    'senior': 7,
    'manager': 10,
}


def extract_keywords(text: str) -> set:
    """
    Extract tech keywords from text using predefined skill list.
    Returns set of matched skills (lowercase).
    """
    if not text:
        return set()
    
    text_lower = text.lower()
    found = set()
    
    for skill in TECH_SKILLS:
        # Use word boundary matching for short skills
        if len(skill) <= 3:
            pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, text_lower):
                found.add(skill)
        else:
            # For longer skills, simple substring match is fine
            if skill in text_lower:
                found.add(skill)
    
    return found


def fuzzy_title_match(job_title: str, target_roles: List[str]) -> float:
    """
    Calculate fuzzy match score between job title and target roles.
    Returns 0.0-1.0 score.
    """
    if not job_title or not target_roles:
        return 0.0
    
    job_title_lower = job_title.lower().strip()
    best_score = 0.0
    
    for role in target_roles:
        if not role:
            continue
        role_lower = role.lower().strip()
        
        # Exact match
        if job_title_lower == role_lower:
            return 1.0
        
        # Contains match
        if role_lower in job_title_lower:
            best_score = max(best_score, 0.9)
        
        # Fuzzy match using difflib
        ratio = difflib.SequenceMatcher(None, job_title_lower, role_lower).ratio()
        best_score = max(best_score, ratio)
    
    return best_score


def calculate_skill_overlap(job_description: str, profile_skills: List[str]) -> float:
    """
    Calculate percentage of job keywords matching profile skills.
    Returns 0.0-1.0 score.
    """
    if not job_description or not profile_skills:
        return 0.0
    
    job_keywords = extract_keywords(job_description)
    if not job_keywords:
        return 0.5  # Neutral if no keywords found
    
    profile_keywords = set()
    for skill in profile_skills:
        if skill:
            skill_lower = skill.lower().strip()
            profile_keywords.add(skill_lower)
            # Also check if skill matches a known tech skill
            for tech in TECH_SKILLS:
                if skill_lower == tech or skill_lower in tech or tech in skill_lower:
                    profile_keywords.add(tech)
    
    if not profile_keywords:
        return 0.0
    
    # Calculate overlap
    overlap = job_keywords.intersection(profile_keywords)
    
    # Score based on how many job requirements are met
    if len(job_keywords) > 0:
        return min(len(overlap) / max(len(job_keywords) * 0.5, 1), 1.0)
    return 0.0


def calculate_location_match(job_location: str, job_remote: bool, profile: dict) -> float:
    """
    Calculate location match score.
    Returns 0.0-1.0 score.
    """
    if not profile:
        return 0.5  # Neutral if no profile
    
    prefs = profile.get('preferences', {})
    remote_pref = prefs.get('remotePreference', 'any')
    target_locations = prefs.get('targetLocations', [])
    profile_location = profile.get('location', '')
    
    # Remote preference matching
    if job_remote:
        if remote_pref == 'remote_only':
            return 1.0
        elif remote_pref == 'any':
            return 0.8
        elif remote_pref == 'hybrid':
            return 0.6
        elif remote_pref == 'onsite':
            return 0.3
    else:
        if remote_pref == 'remote_only':
            return 0.2
        elif remote_pref == 'onsite':
            return 0.8
    
    # Location matching
    job_loc_lower = (job_location or '').lower()
    
    # Check target locations
    for target in target_locations:
        if target and target.lower() in job_loc_lower:
            return 1.0
    
    # Check profile location
    if profile_location and profile_location.lower() in job_loc_lower:
        return 0.9
    
    # Remote jobs are generally acceptable
    if job_remote:
        return 0.7
    
    return 0.5  # Default neutral


def detect_seniority(text: str) -> str:
    """
    Detect seniority level from text.
    Returns 'junior', 'mid', 'senior', 'manager', or 'unknown'.
    """
    if not text:
        return 'unknown'
    
    text_lower = text.lower()
    
    # Check each level (order matters - check more specific first)
    for level, indicators in SENIORITY_LEVELS.items():
        for indicator in indicators:
            if indicator in text_lower:
                return level
    
    return 'unknown'


def calculate_seniority_match(job_title: str, job_description: str, profile: dict) -> float:
    """
    Calculate seniority match based on experience level.
    Returns 0.0-1.0 score.
    """
    if not profile:
        return 0.5  # Neutral
    
    prefs = profile.get('preferences', {})
    exp_level = prefs.get('experienceLevel', 'any')
    
    # Detect job seniority
    job_seniority = detect_seniority(job_title + ' ' + job_description)
    
    if exp_level == 'any' or job_seniority == 'unknown':
        return 0.5  # Neutral
    
    # Map experience level to seniority
    if exp_level in ['entry', 'junior']:
        target = 'junior'
    elif exp_level in ['mid', 'intermediate']:
        target = 'mid'
    elif exp_level in ['senior', 'lead']:
        target = 'senior'
    elif exp_level in ['manager', 'director', 'executive']:
        target = 'manager'
    else:
        return 0.5
    
    # Score based on match
    if job_seniority == target:
        return 1.0
    
    # Adjacent levels get partial score
    levels = ['junior', 'mid', 'senior', 'manager']
    try:
        job_idx = levels.index(job_seniority)
        target_idx = levels.index(target)
        diff = abs(job_idx - target_idx)
        if diff == 1:
            return 0.6
        elif diff == 2:
            return 0.3
        else:
            return 0.1
    except ValueError:
        return 0.5


def calculate_salary_match(job_description: str, profile: dict) -> float:
    """
    Calculate salary match score.
    Returns 0.0-1.0 score. Default 0.5 (neutral) if no salary info.
    """
    # Check if salary is mentioned in job
    salary_patterns = [
        r'\$[\d,]+(?:k|K)?(?:\s*-\s*\$[\d,]+(?:k|K)?)?',
        r'€[\d,]+(?:k|K)?(?:\s*-\s*€[\d,]+(?:k|K)?)?',
        r'£[\d,]+(?:k|K)?(?:\s*-\s*£[\d,]+(?:k|K)?)?',
        r'[\d,]+\s*(?:USD|EUR|GBP|EGP|SAR|AED)\b',
        r'salary.*?[\d,]+',
        r'compensation.*?[\d,]+',
        r'pay.*?[\d,]+',
    ]
    
    has_salary = False
    for pattern in salary_patterns:
        if re.search(pattern, job_description, re.IGNORECASE):
            has_salary = True
            break
    
    if not has_salary:
        return 0.5  # Neutral if no salary mentioned
    
    # If salary is mentioned and profile has salary expectations, do detailed matching
    prefs = profile.get('preferences', {})
    salary_min = prefs.get('salaryMin')
    salary_max = prefs.get('salaryMax')
    
    if not salary_min and not salary_max:
        return 0.5  # Neutral if no salary preference
    
    # Simple heuristic: if salary is mentioned, it's likely competitive
    return 0.7


def calculate_fit_score(job: dict, profile: dict) -> dict:
    """
    Calculate comprehensive fit score for a job against a profile.
    
    Args:
        job: Job dict with keys: title, description, location, remote
        profile: Profile dict with keys: skills, preferences, location, experience
    
    Returns:
        Dict with total score and breakdown
    """
    if not profile:
        return {
            'total': 50,
            'titleMatch': 50,
            'skillOverlap': 50,
            'locationMatch': 50,
            'seniorityMatch': 50,
            'salaryMatch': 50
        }
    
    # Extract job data
    job_title = job.get('title', '')
    job_description = job.get('description', '')
    job_location = job.get('location', '')
    job_remote = job.get('remote', False)
    
    # Extract profile data
    skills = profile.get('skills', [])
    prefs = profile.get('preferences', {})
    target_roles = prefs.get('targetRoles', [])
    
    # If no target roles, try to infer from title
    if not target_roles:
        target_roles = [profile.get('title', '')]
    
    # Calculate individual scores (0-100)
    title_score = fuzzy_title_match(job_title, target_roles) * 100
    skill_score = calculate_skill_overlap(job_description, skills) * 100
    location_score = calculate_location_match(job_location, job_remote, profile) * 100
    seniority_score = calculate_seniority_match(job_title, job_description, profile) * 100
    salary_score = calculate_salary_match(job_description, profile) * 100
    
    # Weighted total
    total = (
        title_score * 0.30 +
        skill_score * 0.35 +
        location_score * 0.15 +
        seniority_score * 0.10 +
        salary_score * 0.10
    )
    
    # Round scores
    return {
        'total': round(total),
        'titleMatch': round(title_score),
        'skillOverlap': round(skill_score),
        'locationMatch': round(location_score),
        'seniorityMatch': round(seniority_score),
        'salaryMatch': round(salary_score)
    }


def score_and_sort_jobs(jobs: List[dict], profile: dict) -> List[dict]:
    """
    Score all jobs and sort by fit score.
    
    Args:
        jobs: List of job dicts
        profile: User profile dict
    
    Returns:
        List of jobs sorted by fit score (highest first)
    """
    if not profile:
        return jobs
    
    scored_jobs = []
    for job in jobs:
        score_result = calculate_fit_score(job, profile)
        job['fit_score'] = score_result['total']
        job['fit_score_breakdown'] = score_result
        scored_jobs.append(job)
    
    # Sort by fit score descending
    scored_jobs.sort(key=lambda j: j.get('fit_score', 0), reverse=True)
    return scored_jobs


# Test function
if __name__ == '__main__':
    test_job = {
        'title': 'Senior Python Developer',
        'description': 'We are looking for a Senior Python Developer with experience in Django, PostgreSQL, Docker, and AWS. The ideal candidate has 5+ years of experience.',
        'location': 'Cairo, Egypt',
        'remote': True
    }
    
    test_profile = {
        'name': 'John Doe',
        'title': 'Python Developer',
        'skills': ['Python', 'Django', 'PostgreSQL', 'Docker', 'AWS', 'FastAPI'],
        'location': 'Cairo',
        'preferences': {
            'targetRoles': ['Python Developer', 'Backend Developer', 'Software Engineer'],
            'targetLocations': ['Cairo', 'Remote'],
            'remotePreference': 'any',
            'experienceLevel': 'senior'
        }
    }
    
    result = calculate_fit_score(test_job, test_profile)
    print(f"Fit Score: {result}")
