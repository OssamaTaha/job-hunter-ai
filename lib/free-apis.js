#!/usr/bin/env node
/**
 * Free Job API Integrations
 * Remotive, Arbeitnow, Jobicy — no API keys required
 */

const https = require('https');
const http = require('http');

/**
 * Strip HTML tags from text
 */
function stripHtml(html) {
  if (!html) return '';
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Truncate text to max length
 */
function truncate(text, maxLen = 500) {
  if (!text) return '';
  if (text.length <= maxLen) return text;
  return text.substring(0, maxLen) + '...';
}

/**
 * Fetch JSON from URL with timeout
 */
function fetchJson(url, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https') ? https : http;
    const timeout = setTimeout(() => {
      reject(new Error('Request timeout'));
    }, timeoutMs);

    const req = client.get(url, {
      headers: {
        'User-Agent': 'JobHunterAI/1.0',
        'Accept': 'application/json'
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        clearTimeout(timeout);
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`JSON parse error: ${e.message}`));
        }
      });
    });

    req.on('error', (e) => {
      clearTimeout(timeout);
      reject(e);
    });

    req.setTimeout(timeoutMs, () => {
      req.destroy();
      reject(new Error('Connection timeout'));
    });
  });
}

/**
 * Normalize job to common format
 */
function normalizeJob(job, source) {
  return {
    id: job.id || `${source}-${Math.random().toString(36).substr(2, 9)}`,
    title: job.title || 'Unknown Position',
    company: job.company || 'Unknown Company',
    location: job.location || 'Remote',
    remote: job.remote || false,
    description: truncate(stripHtml(job.description || ''), 500),
    applyUrl: job.applyUrl || job.url || '#',
    source: source,
    posted: job.posted || null
  };
}

/**
 * Search Remotive API — remote tech jobs
 * https://remotive.com/api/remote-jobs?search=QUERY&limit=20
 */
async function searchRemotive(query, limit = 20) {
  try {
    const url = `https://remotive.com/api/remote-jobs?search=${encodeURIComponent(query)}&limit=${limit}`;
    console.error(`[FreeAPIs] Fetching Remotive: ${url}`);
    
    const data = await fetchJson(url);
    const jobs = (data.jobs || []).map(job => normalizeJob({
      id: `remotive-${job.id}`,
      title: job.title,
      company: job.company_name,
      location: job.candidate_required_location || 'Remote',
      remote: true,
      description: job.description,
      applyUrl: job.url,
      posted: job.publication_date
    }, 'Remotive'));
    
    console.error(`[FreeAPIs] Remotive returned ${jobs.length} jobs`);
    return jobs;
  } catch (e) {
    console.error(`[FreeAPIs] Remotive error: ${e.message}`);
    return [];
  }
}

/**
 * Search Arbeitnow API — EU + remote jobs
 * https://www.arbeitnow.com/api/job-board-api?search=QUERY&page=1
 */
async function searchArbeitnow(query, page = 1) {
  try {
    const url = `https://www.arbeitnow.com/api/job-board-api?search=${encodeURIComponent(query)}&page=${page}`;
    console.error(`[FreeAPIs] Fetching Arbeitnow: ${url}`);
    
    const data = await fetchJson(url);
    const jobs = (data.data || []).map(job => normalizeJob({
      id: `arbeitnow-${job.slug}`,
      title: job.title,
      company: job.company_name,
      location: job.location || 'Remote',
      remote: job.remote || false,
      description: job.description,
      applyUrl: job.url,
      posted: job.created_at
    }, 'Arbeitnow'));
    
    console.error(`[FreeAPIs] Arbeitnow returned ${jobs.length} jobs`);
    return jobs;
  } catch (e) {
    console.error(`[FreeAPIs] Arbeitnow error: ${e.message}`);
    return [];
  }
}

/**
 * Search Jobicy API — remote jobs
 * https://jobicy.com/api/v2/remote-jobs?count=20&tag=QUERY
 */
async function searchJobicy(query, count = 20) {
  try {
    const url = `https://jobicy.com/api/v2/remote-jobs?count=${count}&tag=${encodeURIComponent(query)}`;
    console.error(`[FreeAPIs] Fetching Jobicy: ${url}`);
    
    const data = await fetchJson(url);
    const jobs = (data.jobs || []).map(job => normalizeJob({
      id: `jobicy-${job.id}`,
      title: job.jobTitle,
      company: job.companyGeo || job.companyName || 'Unknown',
      location: job.jobGeo || 'Remote',
      remote: true,
      description: job.jobDescription,
      applyUrl: job.url,
      posted: job.pubDate
    }, 'Jobicy'));
    
    console.error(`[FreeAPIs] Jobicy returned ${jobs.length} jobs`);
    return jobs;
  } catch (e) {
    console.error(`[FreeAPIs] Jobicy error: ${e.message}`);
    return [];
  }
}

/**
 * Search all free APIs in parallel
 * @param {string} query - Job search query
 * @param {string} location - Location filter (not all APIs support this)
 * @returns {Promise<Array>} Combined normalized job results
 */
async function searchAllFreeApis(query, location = '') {
  console.error(`[FreeAPIs] Searching all APIs for: "${query}" in "${location}"`);
  
  const results = await Promise.allSettled([
    searchRemotive(query),
    searchArbeitnow(query),
    searchJobicy(query)
  ]);
  
  const allJobs = [];
  const seenUrls = new Set();
  
  for (const result of results) {
    if (result.status === 'fulfilled') {
      for (const job of result.value) {
        // Deduplicate by applyUrl
        if (job.applyUrl && !seenUrls.has(job.applyUrl)) {
          seenUrls.add(job.applyUrl);
          allJobs.push(job);
        }
      }
    }
  }
  
  console.error(`[FreeAPIs] Total combined jobs: ${allJobs.length}`);
  return allJobs;
}

// CLI mode
if (require.main === module) {
  const args = process.argv.slice(2);
  let input = '';
  
  if (args.length > 0) {
    const query = args[0] || 'developer';
    const location = args[1] || '';
    
    searchAllFreeApis(query, location)
      .then(jobs => console.log(JSON.stringify({ jobs, total: jobs.length })))
      .catch(e => { console.error('Error:', e.message); process.exit(1); });
  } else {
    // Read from stdin
    process.stdin.on('data', chunk => input += chunk);
    process.stdin.on('end', async () => {
      try {
        const params = JSON.parse(input);
        const jobs = await searchAllFreeApis(params.query, params.location);
        console.log(JSON.stringify({ jobs, total: jobs.length }));
      } catch (e) {
        console.error('Error:', e.message);
        console.log(JSON.stringify({ jobs: [], total: 0 }));
      }
    });
  }
}

module.exports = { searchAllFreeApis, searchRemotive, searchArbeitnow, searchJobicy };
