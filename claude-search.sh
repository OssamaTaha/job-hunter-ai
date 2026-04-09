#!/bin/bash
QUERY="$1"
LOCATION="$2"
LIMIT="${3:-10}"
TMPFILE=$(mktemp /tmp/claude-search-XXXXXX.txt)

echo "Searching for $LIMIT $QUERY jobs in $LOCATION via Claude..." >&2

timeout 180 claude -p "You are a job search assistant. Find $LIMIT real, current $QUERY jobs in $LOCATION. Search the web for actual job postings on sites like LinkedIn, Indeed, Glassdoor, Wuzzuf, Bayt, and other job boards.

IMPORTANT: Return ONLY a valid JSON object, no markdown, no explanation, no code fences. Just raw JSON:
{\"jobs\":[{\"title\":\"Job Title\",\"company\":\"Company Name\",\"location\":\"City, Country\",\"url\":\"https://apply-link\",\"source\":\"Site Name\",\"description\":\"Brief description of the role\"}]}

Requirements:
- Only include REAL jobs you find from web search
- Include the actual apply URL for each job
- Include a brief description for each job
- Mark remote jobs with 'Remote' in location
- Return up to $LIMIT jobs
- Output MUST be valid JSON only, nothing else" --print --allowedTools 'WebFetch,WebSearch' --output-format json > "$TMPFILE" 2>/dev/null || true

python3 - "$LIMIT" "$TMPFILE" << 'PYEOF'
import re, json, sys

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10
TMPFILE = sys.argv[2] if len(sys.argv) > 2 else '/tmp/claude-raw.txt'

try:
    with open(TMPFILE, 'r') as f:
        content = f.read()

    import os
    os.unlink(TMPFILE)

    if not content or len(content) < 20:
        print(json.dumps({'jobs': [], 'error': 'empty_output'}))
        sys.exit(0)

    if 'rate limit' in content.lower() or 'RateLimitError' in content:
        print(json.dumps({'error': 'rate_limit', 'jobs': []}))
        sys.exit(0)

    # Clean content
    content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)
    content = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', content)
    # Strip markdown code fences
    content = re.sub(r'```(?:json)?\s*', '', content)

    # Try --output-format json: wraps in {"type":"result","result":"..."}
    try:
        wrapper = json.loads(content)
        if isinstance(wrapper, dict) and 'result' in wrapper:
            inner = wrapper['result']
            if isinstance(inner, str):
                content = inner
            elif isinstance(inner, dict):
                if 'jobs' in inner:
                    inner['jobs'] = inner['jobs'][:LIMIT]
                    print(json.dumps(inner))
                    sys.exit(0)
    except:
        pass

    # Try to find JSON object or array
    start = content.find('{')
    if start < 0:
        start = content.find('[')

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
                        data["jobs"] = data["jobs"][:LIMIT]
                        print(json.dumps(data))
                        sys.exit(0)
            except json.JSONDecodeError:
                pass

    # Fallback: parse markdown/text format with URLs
    jobs = []
    url_pattern = r'(https?://[^\s<>"\'\])\s]+)'
    lines = content.split('\n')

    current_title = ''
    current_company = ''
    current_url = ''
    current_location = 'Egypt'
    current_source = 'Web'
    current_desc = ''

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip meta lines
        skip_words = ["Sources:", "Common Req", "Top Location", "Where to Look", "Volume:", "###"]
        if any(w in line for w in skip_words):
            continue

        # Match "**Title** at Company" or "Title - Company" patterns
        bold_match = re.match(r'\*\*(.+?)\*\*\s*(?:at|[-])\s*(.+?)(?:\s*[-,]|$)', line)
        num_match = re.match(r'^\d+[\.\)]\s*\*?\*?(.+?)\*?\*?\s+(?:at|@|-)\s+(.+?)(?:\s+in\s+|\s*,\s*|\s*\(|$)', line, re.IGNORECASE)
        dash_match = re.match(r'^[-*]\s+\[?(.+?)\]?\(?(https?://[^\s)]+)?\)?\s*[-]\s*(.+)', line)

        match = bold_match or num_match
        if match:
            title = match.group(1).strip().strip('*[]')[:100]
            company = match.group(2).strip().strip('*[]')[:80]

            location = "Egypt"
            line_lower = line.lower()
            if 'cairo' in line_lower: location = "Cairo, Egypt"
            elif 'alexandria' in line_lower: location = "Alexandria, Egypt"
            elif 'remote' in line_lower: location = "Remote"

            url_match = re.search(url_pattern, line)
            url = url_match.group(1).rstrip(')') if url_match else ""

            if title and company and len(title) > 3:
                jobs.append({"title": title, "company": company, "location": location, "url": url, "source": "Web"})
        elif dash_match:
            title = dash_match.group(1).strip()[:100]
            url = (dash_match.group(2) or '').strip()
            rest = dash_match.group(3).strip()[:80]
            if title and len(title) > 3:
                jobs.append({"title": title, "company": rest, "location": "Egypt", "url": url, "source": "Web"})

    # Deduplicate
    seen = set()
    unique_jobs = []
    for job in jobs:
        key = (job.get('title', '') + '|' + job.get('company', '')).lower()
        if key and key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    unique_jobs = unique_jobs[:LIMIT]

    if unique_jobs:
        print(json.dumps({'jobs': unique_jobs}))
    else:
        print(json.dumps({'jobs': [], 'error': 'no_jobs_found', 'preview': content[:500]}))

except Exception as e:
    print(json.dumps({'error': str(e)[:100], 'jobs': []}))
PYEOF
