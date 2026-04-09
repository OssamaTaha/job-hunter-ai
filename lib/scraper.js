#!/usr/bin/env node
/**
 * Claw Job Search - Direct job board visits
 * Uses JSON-LD where available for structured data extraction
 */

const { chromium } = require('playwright');

async function searchJobs(query, location = 'Egypt', remoteOnly = false, maxResults = 50) {
  const allJobs = [];
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 },
  });
  const page = await context.newPage();

  const seen = new Set();

  const addJob = (job) => {
    if (!job.applyUrl || seen.has(job.applyUrl)) return false;
    seen.add(job.applyUrl);
    allJobs.push(job);
    return true;
  };

  try {
    // ==================== RemoteOK ====================
    console.error('[ClawJobSearch] Scraping RemoteOK...');
    try {
      const remoteOkUrl = `https://remoteok.com/?search=${encodeURIComponent(query)}`;
      await page.goto(remoteOkUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(3000);
      
      const remoteCards = await page.$$('tr.job');
      console.error(`[ClawJobSearch] RemoteOK found ${remoteCards.length} results`);
      
      for (const card of remoteCards.slice(0, maxResults)) {
        try {
          const scriptEl = await card.$('script[type="application/ld+json"]');
          let jobData = null;
          
          if (scriptEl) {
            const jsonText = await scriptEl.innerText();
            try {
              jobData = JSON.parse(jsonText);
            } catch {}
          }
          
          if (jobData && jobData.title) {
            const titleEl = await card.$('.preventLink');
            const href = titleEl ? await titleEl.getAttribute('href') : '';
            const applyUrl = href ? `https://remoteok.com${href}` : '';
            
            addJob({
              id: `remoteok-${Buffer.from(applyUrl || jobData.title).toString('base64').slice(0, 12)}`,
              title: jobData.title,
              company: jobData.hiringOrganization?.name || jobData.company || 'Unknown',
              location: 'Remote',
              remote: true,
              description: (jobData.description || '').substring(0, 500),
              applyUrl: applyUrl,
              source: 'RemoteOK',
              posted: jobData.datePosted || null,
            });
          }
        } catch {}
      }
    } catch (e) {
      console.error('[ClawJobSearch] RemoteOK error:', e.message);
    }

    if (allJobs.length >= maxResults) {
      await browser.close();
      return { jobs: allJobs.slice(0, maxResults), total: allJobs.length, sources: ['RemoteOK'] };
    }

    // ==================== Wuzzuf ====================
    console.error('[ClawJobSearch] Scraping Wuzzuf...');
    try {
      const wuzzufUrl = `https://wuzzuf.net/a/ajax/explore/search/?query=${encodeURIComponent(query)}&location=${encodeURIComponent(location)}`;
      await page.goto(wuzzufUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(3000);
      
      const wuzzufCards = await page.$$('.js-result');
      console.error(`[ClawJobSearch] Wuzzuf found ${wuzzufCards.length} results`);
      
      for (const card of wuzzufCards.slice(0, 15)) {
        try {
          const titleEl = await card.$('.job-title a');
          const companyEl = await card.$('.company-name a');
          const locationEl = await card.$('.location a');
          
          if (!titleEl) continue;
          
          const title = await titleEl.innerText();
          const company = companyEl ? await companyEl.innerText() : 'Unknown';
          const loc = locationEl ? await locationEl.innerText() : location;
          const href = await titleEl.getAttribute('href');
          
          if (title && href) {
            addJob({
              id: `wuzzuf-${Buffer.from(href).toString('base64').slice(0, 12)}`,
              title: title.trim(),
              company: company.trim(),
              location: loc.trim(),
              remote: loc.toLowerCase().includes('remote'),
              description: '',
              applyUrl: href.startsWith('http') ? href : `https://wuzzuf.net${href}`,
              source: 'Wuzzuf',
              posted: null,
            });
          }
        } catch {}
      }
    } catch (e) {
      console.error('[ClawJobSearch] Wuzzuf error:', e.message);
    }

    if (allJobs.length >= maxResults) {
      await browser.close();
      return { jobs: allJobs.slice(0, maxResults), total: allJobs.length, sources: ['RemoteOK', 'Wuzzuf'] };
    }

    // ==================== Indeed ====================
    console.error('[ClawJobSearch] Scraping Indeed...');
    try {
      const indeedUrl = `https://eg.indeed.com/jobs?q=${encodeURIComponent(query)}&l=${encodeURIComponent(location)}`;
      await page.goto(indeedUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(3000);
      
      const indeedCards = await page.$$('.jobcard');
      console.error(`[ClawJobSearch] Indeed found ${indeedCards.length} results`);
      
      for (const card of indeedCards.slice(0, 15)) {
        try {
          const titleEl = await card.$('.jobTitle a');
          const companyEl = await card.$('.companyName');
          const locationEl = await card.$('.companyLocation');
          
          if (!titleEl) continue;
          
          const title = await titleEl.innerText();
          const company = companyEl ? await companyEl.innerText() : 'Unknown';
          const loc = locationEl ? await locationEl.innerText() : location;
          const href = await titleEl.getAttribute('href');
          
          if (title && href) {
            addJob({
              id: `indeed-${Buffer.from(href).toString('base64').slice(0, 12)}`,
              title: title.trim(),
              company: company.trim(),
              location: loc.trim(),
              remote: loc.toLowerCase().includes('remote'),
              description: '',
              applyUrl: href.startsWith('http') ? href : `https://eg.indeed.com${href}`,
              source: 'Indeed',
              posted: null,
            });
          }
        } catch {}
      }
    } catch (e) {
      console.error('[ClawJobSearch] Indeed error:', e.message);
    }

    await browser.close();
    const sources = [...new Set(allJobs.map(j => j.source))];
    return { jobs: allJobs.slice(0, maxResults), total: allJobs.length, sources };

  } catch (err) {
    await browser.close();
    throw err;
  }
}

// CLI
if (require.main === module) {
  const args = process.argv.slice(2);
  let input = '';
  
  if (args.length > 0) {
    // Use args: node claw-job-search.js <query> <location> <maxResults>
    const query = args[0] || 'data engineer';
    const location = args[1] || 'Egypt';
    const maxResults = parseInt(args[2]) || 50;
    
    searchJobs(query, location, false, maxResults)
      .then(r => console.log(JSON.stringify(r)))
      .catch(e => { console.error('Error:', e.message); process.exit(1); });
  } else {
    // Read from stdin
    process.stdin.on('data', chunk => input += chunk);
    process.stdin.on('end', async () => {
      try {
        const params = JSON.parse(input);
        const results = await searchJobs(params.query, params.location, params.remoteOnly, params.maxResults);
        console.log(JSON.stringify(results));
      } catch (e) {
        console.error('Error:', e.message);
        process.exit(1);
      }
    });
  }
}

module.exports = { searchJobs };
