const { chromium } = require('playwright');
// Browser: Chromium from Playwright by default. CP_CHANNEL=chrome|msedge uses your installed
// Chrome/Edge; HEADED=1 shows the window (real GPU); CP_SOFTWARE_GL=1 forces a software GPU.
const LAUNCH = { channel: process.env.CP_CHANNEL || undefined, headless: !process.env.HEADED, args: process.env.CP_SOFTWARE_GL ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] };
const base=process.argv[2], q=process.argv[3]||'';
(async()=>{const b=await chromium.launch(LAUNCH);const out={};
// 1. Long session: 120 navigations across student screens, heap + character bookkeeping
{const ctx=await b.newContext({viewport:{width:1366,height:800}});await ctx.addCookies([{name:'mock',value:'student',url:base}]);const p=await ctx.newPage();
 await p.goto(base+'/app'+q);await p.waitForSelector('#root h1');await p.waitForTimeout(1500);
 const cdp=await ctx.newCDPSession(p);const heap=async()=>{await cdp.send('HeapProfiler.collectGarbage');return +(((await cdp.send('Runtime.getHeapUsage')).usedSize)/1e6).toFixed(2);};
 const pages=['courses','path','quiz','graph','materials','analytics','planner','settings','notifications','dashboard','tutor','assignments'];
 const h0=await heap();const samples=[];
 for(let i=0;i<120;i++){await p.evaluate(n=>document.querySelector(`[data-nav="${n}"]`)?.click(),pages[i%pages.length]);await p.waitForTimeout(140);if(i%40===39){await p.waitForTimeout(800);samples.push(await heap());}}
 await p.waitForTimeout(1200);
 const s=await p.evaluate(()=>({domNodes:document.getElementsByTagName('*').length,canvases:document.querySelectorAll('canvas').length,cp3d:window.CP3D&&CP3D.stats?CP3D.stats():null}));
 out.longSession={navigations:120,heapStartMB:h0,heapSamplesMB:samples,...s};await ctx.close();}
// 2. Hidden tab: rendering must stop while hidden and resume when visible
{const ctx=await b.newContext();await ctx.addCookies([{name:'mock',value:'student',url:base}]);const p=await ctx.newPage();await p.goto(base+'/'+q);await p.waitForTimeout(2500);
 out.hiddenTab=await p.evaluate(async()=>{if(!window.CP3D||!CP3D.stats)return 'n/a';const f=()=>CP3D.stats().frames;const a=f();await new Promise(r=>setTimeout(r,1000));const b=f();
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));await new Promise(r=>setTimeout(r,300));const c=f();await new Promise(r=>setTimeout(r,1500));const d=f();
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));await new Promise(r=>setTimeout(r,1500));const e=f();
  return {framesPerSecVisible:b-a,framesWhileHidden1500ms:d-c,framesAfterReturn1500ms:e-d};});await ctx.close();}
// 3. Four tabs open at once
{const ctx=await b.newContext();const t0=Date.now();const ps=await Promise.all([0,1,2,3].map(()=>ctx.newPage()));await Promise.all(ps.map((p,i)=>p.goto(base+(i%2?'/login':'/')+q)));
 const ready=await Promise.all(ps.map(p=>p.waitForSelector('#root h1',{timeout:60000}).then(()=>Date.now()-t0)));
 await ps[0].waitForTimeout(2000);const lag=await ps[0].evaluate(async()=>{const t=performance.now();await new Promise(r=>setTimeout(r,0));return Math.round(performance.now()-t);});
 out.fourTabs={readyMs:ready,setTimeout0LagMs:lag};await ctx.close();}
// 4. Slow network (Slow 4G-like: 150 ms RTT, 1.6 Mbps down), cold cache, landing page
{const ctx=await b.newContext();const p=await ctx.newPage();const cdp=await ctx.newCDPSession(p);await cdp.send('Network.enable');
 await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:200*1024,uploadThroughput:90*1024});
 let bytes=0;p.on('response',async r=>{try{const h=await r.allHeaders();bytes+=Number(h['content-length']||0);}catch{}});
 const t0=Date.now();await p.goto(base+'/'+q);await p.waitForSelector('.hero h1');const ready=Date.now()-t0;await p.waitForTimeout(1500);
 const lcp=await p.evaluate(()=>new Promise(r=>new PerformanceObserver(l=>{const e=l.getEntries();r(Math.round(e[e.length-1].startTime));}).observe({type:'largest-contentful-paint',buffered:true})));
 out.slowNetwork={heroVisibleMs:ready,lcpMs:lcp,transferredKB:Math.round(bytes/1024)};await ctx.close();}
console.log(JSON.stringify(out,null,1));await b.close();})();
