const { chromium } = require('playwright');
// Browser: Chromium from Playwright by default. CP_CHANNEL=chrome|msedge uses your installed
// Chrome/Edge; HEADED=1 shows the window (real GPU); CP_SOFTWARE_GL=1 forces a software GPU.
const LAUNCH = { channel: process.env.CP_CHANNEL || undefined, headless: !process.env.HEADED, args: process.env.CP_SOFTWARE_GL ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] };
const base = process.argv[2], tag = process.argv[3] || 'x';
const widths = [[360,740,'android'],[390,844,'iphone'],[768,1024,'tablet'],[1024,700,'laptop-s'],[1366,800,'laptop'],[1920,1080,'desktop'],[844,390,'phone-landscape']];
const screens = [[null,'/','landing'],[null,'/login','login'],[null,'/register','register'],['student','/app','s-dashboard'],['student','/app#path','s-path'],['student','/app#graph','s-graph'],['student','/app#quiz','s-quiz'],['teacher','/app','t-dashboard'],['teacher','/app#students','t-students'],['admin','/app','admin']];
(async()=>{const b=await chromium.launch(LAUNCH);
const issues=[];let n=0;
for(const [w,h,dev] of widths){const ctx=await b.newContext({viewport:{width:w,height:h},deviceScaleFactor:1,isMobile:w<900&&dev!=='laptop-s',hasTouch:w<900});
 for(const [role,path,name] of screens){ if(role)await ctx.addCookies([{name:'mock',value:role,url:base}]); else await ctx.clearCookies();
  const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(e.message));
  await p.goto(base+path.split('#')[0]); await p.waitForSelector('#root h1',{timeout:20000}).catch(()=>{});
  const nav=path.split('#')[1]; if(nav){await p.evaluate(n=>{const b=document.querySelector(`[data-nav="${n}"]`);b&&b.click();},nav);await p.waitForTimeout(1300);} else await p.waitForTimeout(900);
  const r=await p.evaluate(()=>{const W=document.documentElement.clientWidth;const over=[];document.querySelectorAll('body *').forEach(el=>{const cs=getComputedStyle(el);if(cs.position==='fixed'||el.closest('dialog:not([open]),.sidebar:not(.open)'))return;const rc=el.getBoundingClientRect();if(rc.width&&(rc.right>W+1||rc.left<-1)){let p=el.parentElement,clipped=false;while(p&&p!==document.body){const s=getComputedStyle(p);if(/(hidden|auto|scroll|clip)/.test(s.overflowX)){const pr=p.getBoundingClientRect();if(pr.right<=W+1&&pr.left>=-1){clipped=true;break;}}p=p.parentElement;}if(!clipped)over.push((el.tagName+'.'+[...el.classList].join('.')).slice(0,60)+' r='+Math.round(rc.right));}});return {hscroll:document.documentElement.scrollWidth>W,sw:document.documentElement.scrollWidth,W,over:over.slice(0,5),h1:document.querySelectorAll('h1').length};});
  if(r.hscroll||r.over.length||errs.length) issues.push({dev,w,name,...r,errs});
  if(['landing','s-dashboard','t-dashboard','login'].includes(name)&&['iphone','tablet','desktop'].includes(dev)) await p.screenshot({path:`/tmp/r-${tag}-${dev}-${name}.png`,fullPage:false});
  n++; await p.close(); }
 await ctx.close();}
console.log(`${n} screen/size combinations checked`);console.log(JSON.stringify(issues,null,1));await b.close();})();
