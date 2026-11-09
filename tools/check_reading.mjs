// Optional real Chromium QA; no live account or translation provider involved.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import crypto from 'node:crypto';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || require.resolve('playwright', {paths:[path.resolve(import.meta.dirname,'../runtime/browser'),path.resolve(import.meta.dirname,'..')]}));
const [inputArg, outArg] = process.argv.slice(2);
if (!inputArg || !outArg) throw Error('Usage: node tools/check_reading.mjs input.html new-private-qa-directory');
const input = path.resolve(inputArg), out = path.resolve(outArg);
if (fs.existsSync(out)) throw Error('Use a new QA revision directory');
fs.mkdirSync(out, {recursive:true});
const hash = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const browser = await chromium.launch({headless:true});
const issues = [], requests = [], views = [];
try {
  const page = await browser.newPage();
  page.on('pageerror', e => issues.push(e.message));
  await page.route(/^https?:/, route => {requests.push(route.request().url());return route.abort();});
  await page.goto(pathToFileURL(input).href);
  await page.evaluate(async()=> { await document.fonts.ready; for(const f of document.fonts) await f.load(); });
  for (const [name,width,height] of [['desktop',1200,1000],['mobile',390,844]]) {
    await page.setViewportSize({width,height});
    const state = await page.evaluate(()=> ({
      overflow:document.documentElement.scrollWidth>innerWidth+1,
      fonts:[...document.fonts].map(f=>({family:f.family,status:f.status})),
      images:[...document.images].map(i=>i.complete&&i.naturalWidth>0),
      brokenAnchors:[...document.querySelectorAll('a[href^="#"]')].map(a=>a.hash.slice(1)).filter(id=>!document.getElementById(decodeURIComponent(id)))
    }));
    if(state.overflow || state.fonts.some(f=>f.status!=='loaded') || state.images.includes(false) || state.brokenAnchors.length) issues.push(name+' layout/font/image/anchor issue');
    // Actually exercise the first TOC and the footnote/backlink when present.
    for(const selector of ['nav a','a.footnote-ref','a.footnote-backref']) {
      const link=page.locator(selector).first(); if(await link.count()) await link.click();
    }
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
    views.push({name,width,height,...state});
  }
  await page.setViewportSize({width:794,height:1123});
  await page.emulateMedia({media:'print'});
  const printOverflow = await page.evaluate(()=>[...document.querySelectorAll('table,pre,img')].filter(e=>e.scrollWidth>e.clientWidth+2).map(e=>e.tagName));
  if(printOverflow.length) issues.push('print content overflow');
  const pdf = path.join(out,'reading-test.pdf');
  await page.pdf({path:pdf,preferCSSPageSize:true,printBackground:true,displayHeaderFooter:false,tagged:true});
  const report={scope:'offline real Chromium reading/print template',engine:browser.version(),html_sha256:hash(input),pdf_sha256:hash(pdf),views,network_requests:requests,issues,visual_review:'required_all_pdf_pages',translation_quality:'not_tested',live_account:'not_tested'};
  if(requests.length) issues.push('network resource attempted');
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({ok:!issues.length,engine:report.engine,issues}));
  if(issues.length) process.exitCode=1;
} finally {await browser.close();}
