// Closed-loop HTTP load generator (keep-alive). node load.cjs <base> <concurrency> <seconds>
const http=require('http');const [,,base,C,S]=process.argv;const agent=new http.Agent({keepAlive:true,maxSockets:+C});
const paths=['/','/static/app.js?v=0.9.2','/static/style.css?v=0.9.2','/static/cp3d.js?v=0.9.2','/static/mascot.js?v=0.9.2','/static/motion.css?v=0.9.2'];
const lat=[];let err=0,bytes=0,i=0;const end=Date.now()+S*1000;
function one(){return new Promise(res=>{const t=process.hrtime.bigint();const req=http.get(base+paths[i++%paths.length],{agent,headers:{'accept-encoding':'gzip'},timeout:10000},r=>{r.on('data',d=>bytes+=d.length);r.on('end',()=>{if(r.statusCode!==200)err++;lat.push(Number(process.hrtime.bigint()-t)/1e6);res();});});req.on('error',()=>{err++;res();});req.on('timeout',()=>{req.destroy();});});}
async function worker(){while(Date.now()<end)await one();}
(async()=>{const t0=Date.now();await Promise.all(Array.from({length:+C},worker));const s=(Date.now()-t0)/1000;lat.sort((a,b)=>a-b);const p=q=>lat[Math.floor(lat.length*q)]?.toFixed(1);
console.log(JSON.stringify({concurrency:+C,requests:lat.length,rps:Math.round(lat.length/s),p50:p(.5),p95:p(.95),p99:p(.99),errors:err,errorRate:(err/Math.max(1,lat.length)*100).toFixed(2)+'%',MBperSec:+(bytes/s/1e6).toFixed(1)}));})();
