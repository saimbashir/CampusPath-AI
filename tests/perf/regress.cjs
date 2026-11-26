const { chromium } = require('playwright');
// Browser: Chromium from Playwright by default. CP_CHANNEL=chrome|msedge uses your installed
// Chrome/Edge; HEADED=1 shows the window (real GPU); CP_SOFTWARE_GL=1 forces a software GPU.
const LAUNCH = { channel: process.env.CP_CHANNEL || undefined, headless: !process.env.HEADED, args: process.env.CP_SOFTWARE_GL ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] };
const base=process.argv[2], out=process.argv[3], q=process.argv[4]||'';
(async()=>{const b=await chromium.launch(LAUNCH);const res={};
for(const role of [null,'student','teacher','admin']){const ctx=await b.newContext({viewport:{width:1366,height:800}});if(role)await ctx.addCookies([{name:'mock',value:role,url:base}]);
 const p=await ctx.newPage();const errs=[];p.on('pageerror',e=>errs.push(e.message));p.on('console',m=>{if(m.type()==='error'&&!/401/.test(m.text()))errs.push(m.text().slice(0,120));});
 const snap=async()=>p.evaluate(()=>{const m=document.querySelector('#root').cloneNode(true);m.querySelectorAll('.cp-stage,.cp-slot').forEach(x=>x.remove());return {text:m.innerText.replace(/\s+/g,' ').trim(),buttons:m.querySelectorAll('button').length,forms:m.querySelectorAll('form').length,inputs:m.querySelectorAll('input,select,textarea').length,chars:document.querySelectorAll('.cp-char').length,h1:document.querySelectorAll('h1').length};});
 if(!role){for(const path of ['/','/login','/register']){await p.goto(base+path+q);await p.waitForSelector('#root h1');await p.waitForTimeout(1200);res['guest '+path]=await snap();}
   await p.goto(base+'/'+q);await p.waitForSelector('.hero');await p.click('[data-action="register"]');await p.waitForSelector('#auth-form');res['guest click register']=await snap();
   await p.click('[data-action="theme"]');res['guest theme']=await p.evaluate(()=>document.documentElement.dataset.theme);}
 else{await p.goto(base+'/app'+q);await p.waitForSelector('#root h1');await p.waitForTimeout(1200);
   const navs=await p.evaluate(()=>[...new Set([...document.querySelectorAll('.nav [data-nav]')].map(b=>b.dataset.nav))]);
   for(const n of navs){await p.evaluate(n=>document.querySelector(`.nav [data-nav="${n}"]`).click(),n);await p.waitForTimeout(1300);res[role+' '+n]=await snap();}
   // mobile menu + modal on topic click (student)
   if(role==='student'){await p.evaluate(()=>document.querySelector('.nav [data-nav="dashboard"]').click());await p.waitForTimeout(1300);await p.evaluate(()=>document.querySelector('[data-topic]')?.click());await p.waitForTimeout(500);res['student topic modal']=await p.evaluate(()=>({open:document.querySelector('#modal').open,text:document.querySelector('#modal-body').innerText.slice(0,80)}));}
 }
 res[(role||'guest')+' errors']=errs;await ctx.close();}
require('fs').writeFileSync(out,JSON.stringify(res,null,1));console.log(Object.keys(res).length+' snapshots');await b.close();})();
