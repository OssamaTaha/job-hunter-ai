#!/bin/bash
QUERY="$1"
LOCATION="$2"
LIMIT="${3:-10}"

echo "Searching for $LIMIT $QUERY jobs in $LOCATION..." >&2

timeout 180 hermes chat -q "Find $LIMIT $QUERY jobs in $LOCATION. Use web search. Return as JSON list: [{\"title\":\"\",\"company\":\"\",\"location\":\"\",\"url\":\"\",\"source\":\"\"}]" -t web --provider openrouter -Q 2>/dev/null > /tmp/hermes-raw.txt || true

python3 - "$LIMIT" << 'EOF'
import re, json, sys

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10

try:
    with open('/tmp/hermes-raw.txt', 'r') as f:
        content = f.read()
    
    if not content or len(content) < 20:
        print(json.dumps({'jobs': [], 'error': 'empty_output'}))
        sys.exit(0)
    
    # Check for errors
    if 'rate limit' in content.lower() or 'RateLimitError' in content:
        print(json.dumps({'error': 'rate_limit', 'jobs': []}))
        sys.exit(0)
    
    # Clean content
    content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)
    content = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', content)
    content = re.sub(r'[╭╮╰╯├┤│─]', '', content)
    content = re.sub(r'Session:.*', '', content)
    content = re.sub(r'Resume this session.*', '', content)
    content = re.sub(r'╭─.*╮', '', content)
    content = re.sub(r'╰─.*╯', '', content)
    
    # Try to find JSON first
    start = content.find('[')
    if start < 0:
        start = content.find('{')
    
    if start >= 0:
        brace_count = 0
        in_string = False
        escape = False
        end = start
        
        for i, char in enumerate(content[start:]):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
            elif not in_string:
                if char in '{[':
                    brace_count += 1
                elif char in '}]':
                    brace_count -= 1
                    if brace_count == 0:
                        end = start + i + 1
                        break
        
        if end > start:
            try:
                json_str = content[start:end]
                data = json.loads(json_str)
                if isinstance(data, list):
                    if data:
                        print(json.dumps({'jobs': data[:LIMIT]}))
                        sys.exit(0)
                elif isinstance(data, dict) and "jobs" in data:
                    if data["jobs"]:
                        print(json.dumps(data))
                        sys.exit(0)
            except:
                pass
    
    # Parse text format - look for numbered job entries like:
    # 1. Data Analyst at Company in Location
    # 2. Title at Company (source: Source)
    jobs = []
    url_pattern = r'(https?://[^\s<>"\'\])\s]+)'
    
    # Pattern: number. Title at Company in Location (source: Source)
    # Examples:
    # 1. Data Analyst – Analytics & Knowledge Delivery at EpsilonAI in Nasr City, Cairo - Wuzzuf
    # 2. Data Analyst at Yassir in Cairo, Egypt (source: Wuzzuf)
    
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip non-job lines
        skip_words = ["Reasoning", "web_search", "preparing", "HTTP", "Provider", "API call", 
                     "RateLimit", "Session", "searching", "Let me", "Good", "The user", "I'll",
                     "I need", "From what", "I have", "compiled", "search results"]
        if any(w in line for w in skip_words):
            continue
        
        # Skip lines that are too long or too short
        if len(line) < 15 or len(line) > 300:
            continue
            
        # Look for job pattern: "number. Title at Company" or "number. Title - Company"
        match = re.match(r'^\d+[\.\)]\s*(.+?)\s+(?:at|@|-)\s+(.+?)(?:\s+in\s+|\s*,\s*|\s*\(|$)', line, re.IGNORECASE)
        
        if match:
            title = match.group(1).strip()
            company = match.group(2).strip()
            
            # Clean title (remove source info)
            if '(' in title:
                title = title.split('(')[0].strip()
            if '-' in title:
                title = title.split('-')[0].strip()
            
            title = title[:100]
            company = company[:80]
            
            # Find location
            location = "Egypt"
            line_lower = line.lower()
            if 'cairo' in line_lower:
                location = "Cairo, Egypt"
            elif 'alexandria' in line_lower:
                location = "Alexandria, Egypt"
            elif 'giza' in line_lower:
                location = "Giza, Egypt"
            elif 'remote' in line_lower:
                location = "Remote"
            
            # Find URL
            url_match = re.search(url_pattern, line)
            url = url_match.group(1) if url_match else ""
            
            # Find source
            source = "Web"
            source_match = re.search(r'\(source:\s*([^)]+)\)', line, re.IGNORECASE)
            if source_match:
                source = source_match.group(1).strip()
            elif url:
                domain = re.sub(r'https?://(www\.)?', '', url)
                domain = re.sub(r'/.*', '', domain)
                source = domain.split('.')[0] if '.' in domain else domain
            
            if title and company and len(title) > 3:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "source": source
                })
    
    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in jobs:
        key = (job.get('title', '') or '') + '|' + (job.get('company', '') or '')
        if key and key not in seen:
            seen.add(key)
            unique_jobs.append(job)
    
    unique_jobs = unique_jobs[:LIMIT]
    
    if unique_jobs:
        print(json.dumps({'jobs': unique_jobs}))
    else:
        print(json.dumps({'jobs': [], 'error': 'no_jobs_found', 'preview': content[1000:1500]}))
        
except Exception as e:
    print(json.dumps({'error': str(e)[:100], 'jobs': []}))
EOF
