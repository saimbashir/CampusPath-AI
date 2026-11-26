const { chromium } = require('playwright');
const B='http://127.0.0.1:8102';
(async()=>{const b=await chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const look=p=>p.evaluate(()=>({stats:(({ready,failed,reason,frames})=>({ready,failed,reason,frames}))(CP3D.stats()),canvas3d:document.querySelectorAll('.cp-char canvas').length,waiting:document.querySelectorAll('.cp-wait').length,emoji:document.querySelectorAll('.cp-fallback:not(.cp-wait)').length,visibleChars:[...document.querySelectorAll('.cp-char')].filter(c=>c.offsetWidth).length,guard:localStorage.getItem('cp3d-guard'),bubble:document.querySelector('.cp-say-text')?.textContent}));
// A. normal 3D start, every check active
let ctx=await b.newContext();let p=await ctx.newPage();await p.goto(B+'/?cp3d=guardtest');await p.waitForTimeout(5000);console.log('A normal start   ',JSON.stringify(await look(p)));
// B. same device reloads: guard says ok -> 3D again
await p.goto(B+'/?cp3d=guardtest');await p.waitForTimeout(4000);console.log('B reload after ok',JSON.stringify(await look(p)));
// C. previous start froze (leftover "starting", never ok) -> emoji, no 3D work at all
await p.evaluate(()=>{const g=JSON.parse(localStorage.getItem('cp3d-guard'));g.state='starting';g.wasOk=false;localStorage.setItem('cp3d-guard',JSON.stringify(g));});
await p.goto(B+'/?cp3d=guardtest');await p.waitForTimeout(3000);console.log('C after a freeze ',JSON.stringify(await look(p)));
// D. reset brings 3D back
await p.goto(B+'/?cp3d=reset');await p.goto(B+'/?cp3d=guardtest');await p.waitForTimeout(4000);console.log('D after reset    ',JSON.stringify(await look(p)));await ctx.close();
// E. GPU driver returns blank frames -> emoji instead of empty boxes
ctx=await b.newContext();p=await ctx.newPage();await p.addInitScript(()=>{const o=CanvasRenderingContext2D.prototype.drawImage;CanvasRenderingContext2D.prototype.drawImage=function(src,...a){if(src instanceof HTMLCanvasElement&&!src.isConnected)return;return o.call(this,src,...a);};});
await p.goto(B+'/?cp3d=guardtest');await p.waitForTimeout(5000);console.log('E blank frames   ',JSON.stringify(await look(p)));await ctx.close();
// F. default on this software-GPU machine: emoji immediately; and demo login works
ctx=await b.newContext();p=await ctx.newPage();await p.goto(B+'/');await p.waitForTimeout(2000);console.log('F default        ',JSON.stringify(await look(p)));
console.log('  demo_mode on landing:',await p.evaluate(()=>state.health&&state.health.demo_mode));await ctx.close();
await b.close();})();
