// Reproducible synthetic PDF source, no book/customer data.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || require.resolve('playwright', {paths:[path.resolve(import.meta.dirname,'../runtime/browser'),path.resolve(import.meta.dirname,'..')]}));
const root=path.resolve(import.meta.dirname,'..'), dir=path.join(root,'tests/fixtures/v2');
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const font=fs.readFileSync(path.join(root,'assets/fonts/Vazirmatn-Regular.ttf')).toString('base64');
const browser=await chromium.launch({headless:true});
try {
  for(const name of ['nonfa','persian']) {
    const spec=JSON.parse(fs.readFileSync(path.join(dir,name+'.json'),'utf8'));
    const pages=[...new Set(spec.reconstruction.raw_blocks.map(b=>b.pdf_page))];
    const isFa=name==='persian';
    const block=b=> {
      if(b.columns) return '<p>Table 1'+(b.id==='t2'?' (continued)':'')+'</p><table><thead><tr>'+b.columns.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+b.rows.map(r=>'<tr>'+r.map(c=>'<td>'+esc(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
      const text=esc(b.text).replaceAll('\n','<br>');
      if(b.id.startsWith('h') || b.id==='fh') return '<h2>'+text+'</h2>';
      if(/^f[123]$/.test(b.id)) return '<footer>'+text+' — '+esc(b.printed_page)+'</footer>';
      if(b.id==='note') return '<aside>1. '+text+'</aside>';
      return '<p>'+text+'</p>';
    };
    const sections=pages.map(p=> {
      const blocks=spec.reconstruction.raw_blocks.filter(b=>b.pdf_page===p);
      let body='';
      for(let i=0;i<blocks.length;i++) {
        if(blocks[i].id==='left') {body+='<div class="columns">'+block(blocks[i])+block(blocks[++i])+'</div>';}
        else body+=block(blocks[i]);
      }
      return '<section>'+body+'</section>';
    }).join('');
    const doc=`<!doctype html><html lang="${isFa?'fa':'en'}" dir="${isFa?'rtl':'ltr'}"><meta charset="utf-8"><style>
    @font-face{font-family:Vazirmatn;src:url(data:font/ttf;base64,${font})} @page{size:A4;margin:0}
    body{margin:0;font:16px/1.8 Vazirmatn,sans-serif;color:#111}section{position:relative;box-sizing:border-box;height:297mm;padding:22mm;break-after:page}section:last-child{break-after:auto}h2{margin-top:0}footer{position:absolute;bottom:16mm;font-size:12px;color:#555}.columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{border:1px solid #555;padding:8px}aside{margin-top:40px;border-top:1px solid #aaa}
    </style>${sections}</html>`;
    const page=await browser.newPage();await page.setContent(doc);await page.evaluate(()=>document.fonts.ready);
    await page.pdf({path:path.join(dir,name+'.pdf'),preferCSSPageSize:true,printBackground:true});await page.close();
    console.log(name+': '+pages.length+' synthetic PDF pages');
  }
}finally{await browser.close();}
