/* CampusPath AI · CP3D — a tiny real-time 3D renderer for the app's characters (v0.9.5, performance release).
   Characters are signed-distance-field models ray-marched on the GPU (WebGL 1):
   soft-vinyl bodies with smoothly blended arms and legs (they can never detach), real eyeballs
   that rotate to follow the 3D objects orbiting around them, painted expressions, accessories
   and props. One shared WebGL context renders every character, then copies the frame into each
   character's own <canvas>, so any number of characters can be on a page.
   No libraries, no network, CSP-safe. Falls back to a plain emoji if WebGL is unavailable. */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ shader */
  const VS = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FS = `
precision highp float;
uniform vec2 uRes; uniform float uTime;
uniform vec3 uPos; uniform mat3 uRot;
uniform int uBody; uniform vec3 uBC; uniform vec3 uBR;
uniform vec3 uCol; uniform vec3 uFoot; uniform vec3 uIris; uniform vec3 uAccA; uniform vec3 uAccB;
uniform vec3 uSL; uniform vec3 uSR; uniform vec3 uEL; uniform vec3 uER; uniform vec3 uHL; uniform vec3 uHR;
uniform vec3 uHipL; uniform vec3 uHipR; uniform vec3 uKL; uniform vec3 uKR; uniform vec3 uFL; uniform vec3 uFR;
uniform vec3 uEyeL; uniform vec3 uEyeR; uniform float uEyeRad; uniform vec3 uLook; uniform vec3 uLid;
uniform int uEyeStyle; uniform int uMouth; uniform int uBrow; uniform float uTalk; uniform float uBlush; uniform float uTears;
uniform vec3 uFace; uniform vec3 uTop; uniform int uAcc1; uniform int uAcc2;
uniform int uProp; uniform vec3 uPP; uniform mat3 uPR; uniform vec3 uPA; uniform vec3 uPB; uniform vec3 uPC;
uniform vec4 uOrb[4]; uniform vec3 uOC0; uniform vec3 uOC1; uniform vec3 uOC2; uniform vec3 uOC3;
uniform vec3 uCamPos; uniform vec3 uCamTgt; uniform float uTanF; uniform float uShadow;
uniform vec2 uOff;

vec2 res;
#define U(dd,mm) { float d_=(dd); if(d_<res.x) res=vec2(d_,mm); }

float smin(float a,float b,float k){float h=clamp(.5+.5*(b-a)/k,0.,1.);return mix(b,a,h)-k*h*(1.-h);}
float sdEll(vec3 p,vec3 r){float k0=length(p/r);float k1=length(p/(r*r));return k0*(k0-1.)/max(k1,1e-4);}
float sdCap(vec3 p,vec3 a,vec3 b,float r){vec3 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/dot(ba,ba),0.,1.);return length(pa-ba*h)-r;}
float sdRBox(vec3 p,vec3 b,float r){vec3 q=abs(p)-b;return length(max(q,0.))+min(max(q.x,max(q.y,q.z)),0.)-r;}
float sdTor(vec3 p,vec2 t){return length(vec2(length(p.xz)-t.x,p.y))-t.y;}
float sdCyl(vec3 p,float h,float r){vec2 d=abs(vec2(length(p.xz),p.y))-vec2(r,h);return min(max(d.x,d.y),0.)+length(max(d,0.));}
float sdRCone(vec3 p,vec3 a,vec3 b,float r1,float r2){
  vec3 ba=b-a;float l2=dot(ba,ba);float rr=r1-r2;float a2=l2-rr*rr;float il2=1./l2;
  vec3 pa=p-a;float y=dot(pa,ba);float z=y-l2;vec3 xv=pa*l2-ba*y;float x2=dot(xv,xv);float y2=y*y*l2;float z2=z*z*l2;
  float k=sign(rr)*rr*rr*x2;
  if(sign(z)*a2*z2>k) return sqrt(x2+z2)*il2-r2;
  if(sign(y)*a2*y2<k) return sqrt(x2+y2)*il2-r1;
  return (sqrt(x2*a2*il2)+y*rr)*il2-r1;}
float seg2(vec2 p,vec2 a,vec2 b){vec2 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/dot(ba,ba),0.,1.);return length(pa-ba*h);}
float dot2(vec2 v){return dot(v,v);}
float sdStar5(vec2 p,float r,float rf){
  vec2 k1=vec2(0.809016994375,-0.587785252292);vec2 k2=vec2(-k1.x,k1.y);
  p.x=abs(p.x);p-=2.*max(dot(k1,p),0.)*k1;p-=2.*max(dot(k2,p),0.)*k2;p.x=abs(p.x);p.y-=r;
  vec2 ba=rf*vec2(-k1.y,k1.x)-vec2(0.,1.);float h=clamp(dot(p,ba)/dot(ba,ba),0.,r);
  return length(p-ba*h)*sign(p.y*ba.x-p.x*ba.y);}
float sdHeart(vec2 p){p.x=abs(p.x);if(p.y+p.x>1.)return sqrt(dot2(p-vec2(.25,.75)))-.353553;
  return sqrt(min(dot2(p-vec2(0.,1.)),dot2(p-.5*max(p.x+p.y,0.))))*sign(p.x-p.y);}
float ext(float d,float z,float h){vec2 w=vec2(d,abs(z)-h);return min(max(w.x,w.y),0.)+length(max(w,0.));}
mat2 r2(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}

float bodySD(vec3 q){
  if(uBody==1) return sdCap(q,uBC-vec3(0.,uBR.y,0.),uBC+vec3(0.,uBR.y,0.),uBR.x);
  if(uBody==2) return sdRBox(q-uBC,uBR,.27);
  if(uBody==3) return sdRCone(q,uBC,uBC+vec3(0.,uBR.y,0.),uBR.x,uBR.z);
  return sdEll(q-uBC,uBR);
}

void acc(int id,vec3 q){
  vec3 t=q-uTop;
  if(id!=3&&id!=4&&length(t)-.9>res.x) return; /* perf: bounding sphere */
  if(id==1){ /* sprout */
    U(sdCap(t,vec3(0.,-.06,0.),vec3(0.,.2,0.),.028),18.);
    vec3 a=t-vec3(-.11,.23,0.);a.xy=r2(-.5)*a.xy;U(sdEll(a,vec3(.13,.045,.08)),18.);
    vec3 b=t-vec3(.11,.25,0.);b.xy=r2(.55)*b.xy;U(sdEll(b,vec3(.12,.045,.075)),18.);
  } else if(id==2){ /* graduation cap */
    U(sdCyl(t-vec3(0.,-.04,0.),.09,.4),9.);
    vec3 b=t-vec3(0.,.07,0.);b.xz=r2(.785)*b.xz;b.xy=r2(.06)*b.xy;U(sdRBox(b,vec3(.5,.012,.5),.012),9.);
    U(length(t-vec3(0.,.1,0.))-.035,7.);
    U(sdCap(t,vec3(0.,.1,0.),vec3(.46,.08,.18),.012),7.);
    U(sdCap(t,vec3(.46,.08,.18),vec3(.47,-.12+.02*sin(uTime*3.),.2),.016),7.);
    U(sdEll(t-vec3(.47,-.17+.02*sin(uTime*3.),.2),vec3(.04,.07,.04)),7.);
  } else if(id==3){ /* round glasses */
    for(int i=0;i<2;i++){ vec3 e=(i==0?uEyeL:uEyeR)+vec3(0.,0.,uEyeRad*.85); vec3 g=q-e; U(length(vec2(length(g.xy)-uEyeRad*1.38,g.z))-.022,9.); }
    U(sdCap(q,uEyeL+vec3(uEyeRad*1.3,.04,uEyeRad*.85),uEyeR+vec3(-uEyeRad*1.3,.04,uEyeRad*.85),.02),9.);
  } else if(id==4){ /* headphones */
    vec3 h=q-vec3(uBC.x,uBC.y+.05,uBC.z); float R=uBR.x+.05;
    float band=length(vec2(length(h.xy)-R,h.z))-.045; band=max(band,-(h.y-.05)); U(band,19.);
    U(sdEll(h-vec3(-R,.0,0.),vec3(.1,.19,.16)),5.); U(sdEll(h-vec3(R,.0,0.),vec3(.1,.19,.16)),5.);
    U(sdCap(q,vec3(uBC.x-R+.02,uBC.y-.05,.12),uFace+vec3(-.2,.02,.1),.022),9.);
    U(length(q-(uFace+vec3(-.2,.02,.12)))-.055,6.);
  } else if(id==5){ /* crown */
    vec3 c=t-vec3(0.,.02,0.); float ring=sdCyl(c,.07,.3); ring=max(ring,-sdCyl(c,.2,.25)); U(ring,7.);
    float a=atan(c.z,c.x); float sec=1.2566; a=mod(a+sec*.5,sec)-sec*.5; float L=length(c.xz); vec3 s=vec3(cos(a)*L,c.y,sin(a)*L);
    U(sdRCone(s,vec3(.28,.05,0.),vec3(.28,.2,0.),.06,.015),7.);
    U(length(c-vec3(0.,.02,.31))-.045,17.);
  } else if(id==6){ /* halo */
    U(sdTor(t-vec3(0.,.3+.035*sin(uTime*2.),0.),vec2(.34,.038)),10.);
  } else if(id==7){ /* antenna */
    U(sdCap(t,vec3(0.,-.05,0.),vec3(.04,.32,0.),.028),23.);
    U(length(t-vec3(.04,.36,0.))-.085,19.);
  } else if(id==8){ /* party hat */
    vec3 c=t-vec3(-.05,-.06,0.); c.xy=r2(.18)*c.xy;
    U(sdRCone(c,vec3(0.,0.,0.),vec3(0.,.58,0.),.26,.02),20.);
    U(length(c-vec3(0.,.6,0.))-.075,6.);
  } else if(id==9){ /* baseball cap */
    vec3 c=t-vec3(0.,-.16,0.); float dome=max(sdEll(c,vec3(.56,.32,.56)),-c.y+.02); U(dome,5.);
    U(sdEll(t-vec3(0.,-.14,.5),vec3(.34,.03,.26)),6.);
    U(length(t-vec3(0.,.15,0.))-.04,6.);
  } else if(id==10){ /* beanie */
    vec3 c=t-vec3(0.,-.18,0.); float dome=max(sdEll(c,vec3(.6,.4,.58)),-c.y+.06); U(dome,5.);
    U(sdTor(c-vec3(0.,.08,0.),vec2(.56,.07)),6.);
    U(length(t-vec3(0.,.24,0.))-.1,6.);
  } else if(id==11){ /* bow */
    vec3 c=t-vec3(.3,-.12,.12); c.xy=r2(-.5)*c.xy;
    U(sdEll(c-vec3(-.13,0.,0.),vec3(.14,.09,.06)),5.); U(sdEll(c-vec3(.13,0.,0.),vec3(.14,.09,.06)),5.);
    U(length(c)-.06,6.);
  } else if(id==12){ /* beret */
    vec3 c=t-vec3(-.08,.0,0.); c.xy=r2(.2)*c.xy; U(sdEll(c,vec3(.46,.11,.42)),5.); U(length(c-vec3(0.,.12,0.))-.04,5.);
  } else if(id==13){ /* rain cloud */
    vec3 c=t-vec3(0.,.34+.03*sin(uTime*2.),0.);
    float cl=length(c-vec3(-.15,0.,0.))-.15; cl=smin(cl,length(c-vec3(.12,.02,0.))-.17,.08); cl=smin(cl,length(c-vec3(0.,.1,0.))-.16,.08); U(cl,22.);
    for(int i=0;i<3;i++){ float fi=float(i); float y=fract(uTime*1.3+fi*.33); U(length(c-vec3(-.14+fi*.14,-.2-y*.45,0.))-.03*(1.-y*.5),11.); }
  }
}

void prop(vec3 q){
  if(uProp==0) return;
  if(length(q-uPP)-(uProp==14?.9:.72)>res.x) return; /* perf: bounding sphere */
  vec3 p=uPR*(q-uPP);
  if(uProp==1){ U(length(p-vec3(0.,.17,0.))-.15,10.); U(sdCyl(p-vec3(0.,-.0,0.),.06,.075),23.); U(sdTor(p-vec3(0.,.02,0.),vec2(.075,.015)),9.); }
  else if(uProp==2){ vec3 r=p-vec3(0.,.14,0.); U(length(vec2(length(r.xy)-.07,r.z))-.026,7.); U(sdCap(p,vec3(0.,.07,0.),vec3(0.,-.2,0.),.025),7.); U(sdRBox(p-vec3(.04,-.15,0.),vec3(.03,.012,.012),.004),7.); U(sdRBox(p-vec3(.035,-.2,0.),vec3(.025,.012,.012),.004),7.); }
  else if(uProp==3){ vec3 c=p.xzy; U(sdCyl(c,.03,.16)-.01,7.); U(sdCyl(c-vec3(0.,.03,0.),.008,.13),8.); vec3 n=p-vec3(0.,0.,.045); n.xy=r2(sin(uTime*1.7)*.8)*n.xy; U(sdRBox(n,vec3(.012,.1,.006),.003),17.); }
  else if(uProp==4){ for(int i=0;i<2;i++){ float s=i==0?-1.:1.; vec3 c=p-vec3(s*.18,0.,0.); c.xz=r2(s*.35)*c.xz; U(sdRBox(c,vec3(.17,.24,.008),.008),12.); U(sdRBox(c-vec3(0.,0.,.016),vec3(.155,.225,.008),.004),8.); } }
  else if(uProp==5){ U(sdCap(p,vec3(0.,-.2,0.),vec3(0.,.18,0.),.045),12.); U(sdRCone(p,vec3(0.,-.2,0.),vec3(0.,-.31,0.),.045,.008),24.); U(sdCyl(p-vec3(0.,.22,0.),.04,.046),15.); }
  else if(uProp==6){ vec3 r=p-vec3(0.,.12,0.); U(length(vec2(length(r.xy)-.13,r.z))-.03,9.); U(sdCyl(r.xzy,.01,.11),16.); U(sdCap(p,vec3(.07,.01,0.),vec3(.18,-.18,0.),.03),12.); }
  else if(uProp==7){ U(length(p-vec3(0.,.12,0.))-.1,23.); U(sdRCone(p,vec3(0.,.04,0.),vec3(0.,-.22,0.),.05,.035),9.); U(sdTor(p-vec3(0.,.05,0.),vec2(.07,.018)),12.); }
  else if(uProp==8){ vec3 c=p.xzy; U(sdCyl(c,.045,.19)-.01,12.); U(sdCyl(c-vec3(0.,.05,0.),.005,.16),8.);
    vec3 h=p-vec3(0.,0.,.06); vec3 m=h; m.xy=r2(-uTime*2.)*m.xy; U(sdRBox(m-vec3(0.,.06,0.),vec3(.01,.065,.005),.003),9.); vec3 hh=h; hh.xy=r2(-uTime*.2)*hh.xy; U(sdRBox(hh-vec3(0.,.04,0.),vec3(.012,.045,.005),.003),9.);
    U(length(p-vec3(-.13,.17,0.))-.06,7.); U(length(p-vec3(.13,.17,0.))-.06,7.); }
  else if(uProp==9){ U(sdRBox(p,vec3(.3,.018,.2),.012),23.); vec3 s=p-vec3(0.,.02,-.2); s.yz=r2(-.25)*s.yz; s-=vec3(0.,.21,0.); U(sdRBox(s,vec3(.3,.21,.012),.012),23.); U(sdRBox(s-vec3(0.,0.,.015),vec3(.27,.18,.004),.002),25.); }
  else if(uProp==10){ U(sdRBox(p,vec3(.24,.015,.08),.01),8.); for(int i=0;i<3;i++){ float fi=float(i); float h=.08+.07*fi+.03*sin(uTime*2.+fi); U(sdRBox(p-vec3(-.15+fi*.15,h+.02,0.),vec3(.05,h,.05),.012),12.+fi); } }
  else if(uProp==11){ vec3 b=p; b.xy=r2(sin(uTime*7.)*.35)*b.xy; float d=max(sdEll(b-vec3(0.,.02,0.),vec3(.15,.17,.15)),-(b.y+.02)); U(d,7.); U(sdTor(b-vec3(0.,-.02,0.),vec2(.15,.022)),7.); U(length(b-vec3(0.,-.06,0.))-.04,9.); U(sdTor((b-vec3(0.,.2,0.)).xzy,vec2(.04,.012)),7.); }
  else if(uProp==12){ U(sdEll(p,vec3(.22,.27,.05)),12.); U(ext(sdStar5(p.xy,.1,.45),p.z-.05,.012)-.006,7.); }
  else if(uProp==13){ U(sdRBox(p,vec3(.22,.15,.012),.012),8.); vec3 f=p-vec3(0.,.03,.02); U(ext(min(seg2(f.xy,vec2(-.2,.1),vec2(0.,-.04)),seg2(f.xy,vec2(.2,.1),vec2(0.,-.04)))-.012,f.z,.004),24.); U(length(p-vec3(0.,-.03,.03))-.035,17.); }
  else if(uProp==14){ U(sdCap(p,vec3(0.,-.1,0.),vec3(0.,.75,0.),.02),24.); U(length(p-vec3(0.,.77,0.))-.04,17.); }
  else if(uProp==15){ vec3 h=p; h.y+=.12; float s=.28; U(ext(sdHeart(h.xy/s)*s,h.z,.05)-.03,17.); }
  else if(uProp==16){ float cup=sdRCone(p,vec3(0.,.06,0.),vec3(0.,.26,0.),.07,.17); cup=max(cup,-sdRCone(p,vec3(0.,.1,0.),vec3(0.,.3,0.),.05,.15)); U(cup,7.);
    U(sdTor((p-vec3(-.18,.18,0.)).xzy,vec2(.06,.015)),7.); U(sdTor((p-vec3(.18,.18,0.)).xzy,vec2(.06,.015)),7.);
    U(sdCyl(p-vec3(0.,0.,0.),.06,.025),7.); U(sdRBox(p-vec3(0.,-.07,0.),vec3(.1,.025,.08),.01),9.); U(ext(sdStar5((p-vec3(0.,.17,.15)).xy,.04,.45),p.z-.15,.008),10.); }
  else if(uProp==17){ U(sdRBox(p,vec3(.19,.26,.012),.012),24.); U(sdRBox(p-vec3(0.,-.02,.016),vec3(.16,.21,.004),.002),8.); U(sdRBox(p-vec3(0.,.25,.02),vec3(.07,.03,.015),.008),23.);
    for(int i=0;i<3;i++){ float fi=float(i); U(sdRBox(p-vec3(.02,.1-fi*.09,.022),vec3(.1,.008,.002),.002),9.); U(ext(min(seg2((p-vec3(-.11,.1-fi*.09,0.)).xy,vec2(-.02,0.),vec2(0.,-.02)),seg2((p-vec3(-.11,.1-fi*.09,0.)).xy,vec2(0.,-.02),vec2(.035,.025)))-.008,p.z-.024,.003),18.); } }
  else if(uProp==18){ U(length(p-vec3(0.,.0,0.))-.15,26.); U(sdCyl(p-vec3(0.,.17,0.),.08,.045),16.); U(sdTor(p-vec3(0.,.25,0.),vec2(.05,.012)),16.); }
}

void orbs(vec3 p){
  for(int i=ZERO;i<4;i++){
    vec4 o=uOrb[i]; if(o.w<-.5) continue;
    if(length(p-o.xyz)-.3>res.x) continue; /* perf: bounding sphere */
    vec3 c=p-o.xyz; float m=30.+float(i); float sp=uTime*1.4+float(i);
    c.xz=r2(sp)*c.xz; c.xy=r2(.4)*c.xy;
    float t=o.w; float s=.13;
    if(t<.5) U(length(c)-s,m)
    else if(t<1.5) U(ext(sdStar5(c.xy,s*1.25,.45),c.z,.035)-.025,m)
    else if(t<2.5) U(sdTor(c.xzy,vec2(s*.9,.035)),m)
    else if(t<3.5) U(sdRBox(c,vec3(s*.62),.04),m)
    else if(t<4.5){ vec3 h=c; h.y+=s*.5; U(ext(sdHeart(h.xy/(s*1.1))*s*1.1,h.z,.03)-.03,m); }
    else if(t<5.5) U(ext(min(seg2(c.xy,vec2(-.11,0.),vec2(-.03,-.08)),seg2(c.xy,vec2(-.03,-.08),vec2(.12,.1)))-.035,c.z,.02)-.01,m)
    else U((abs(c.x)+abs(c.y)+abs(c.z)-s*1.2)*.577,m)
  }
}

vec2 map(vec3 p){
  res=vec2(1e5,0.);
  vec3 q=uRot*(p-uPos)+vec3(0.,1.,0.);
  float d=bodySD(q);
  d=smin(d,sdCap(q,uSL,uEL,.105),.1); d=smin(d,sdCap(q,uEL,uHL,.095),.04); d=smin(d,length(q-uHL)-.13,.04);
  d=smin(d,sdCap(q,uSR,uER,.105),.1); d=smin(d,sdCap(q,uER,uHR,.095),.04); d=smin(d,length(q-uHR)-.13,.04);
  d=smin(d,sdCap(q,uHipL,uKL,.115),.08); d=smin(d,sdCap(q,uKL,uFL,.1),.03);
  d=smin(d,sdCap(q,uHipR,uKR,.115),.08); d=smin(d,sdCap(q,uKR,uFR,.1),.03);
  res=vec2(d,1.);
  U(sdEll(q-uFL-vec3(0.,-.01,.07),vec3(.15,.085,.21)),4.);
  U(sdEll(q-uFR-vec3(0.,-.01,.07),vec3(.15,.085,.21)),4.);
  if(uEyeStyle==0){ U(length(q-uEyeL)-uEyeRad,2.); U(length(q-uEyeR)-uEyeRad,3.); }
  else if(uEyeStyle==2){ for(int i=0;i<2;i++){ vec3 e=q-(i==0?uEyeL:uEyeR); e.xy=r2(uTime*1.6+float(i))*e.xy; U(ext(sdStar5(e.xy,uEyeRad*1.35,.45),e.z,.04)-.02,7.); } }
  if(uTears>.5){ for(int i=0;i<2;i++){ vec3 e=i==0?uEyeL:uEyeR; float y=fract(uTime*1.1+float(i)*.5); U(length(q-e-vec3((i==0?-.06:.06),-.3-y*.55,.05-y*.1))-.045*(1.-y*.6),11.); } }
  for(int k=ZERO;k<2;k++){ int id=k==0?uAcc1:uAcc2; if(id>0) acc(id,q); } /* one inlined copy on WebGL2 */
  prop(q);
  orbs(p);
  return res;
}

vec3 calcN(vec3 p){vec3 n=vec3(0.);for(int i=ZERO;i<4;i++){vec3 e=vec3((i==0||i==3)?1.:-1.,i>=2?1.:-1.,(i==1||i==3)?1.:-1.);n+=e*map(p+e*.0015).x;}return normalize(n);}
float calcAO(vec3 p,vec3 n){float o=0.,s=1.;for(int i=ZERO;i<4;i++){float h=.02+.07*float(i);o+=(h-map(p+n*h).x)*s;s*=.75;}return clamp(1.-1.6*o,0.,1.);}

vec3 paintFace(vec3 q,vec3 c){
  if(q.z<0.) return c;
  float aa=.007;
  vec3 dark=vec3(.16,.05,.07); vec3 tongue=vec3(.96,.38,.46);
  /* blush */
  if(uBlush>0.){ for(int i=0;i<2;i++){ vec3 e=i==0?uEyeL:uEyeR; vec2 b=(q.xy-vec2(e.x*1.55,e.y-.2))/vec2(.11,.065); c=mix(c,vec3(1.,.45,.55),uBlush*.5*(1.-smoothstep(.4,1.,length(b)))); } }
  /* painted eyes */
  for(int i=0;i<2;i++){
    vec3 e=i==0?uEyeL:uEyeR; vec2 f=q.xy-e.xy; float d=1.;
    if(uEyeStyle==1){ vec2 o=f-vec2(0.,-.05); d=abs(length(o)-.1)-.024; d=max(d,-(o.y-.035)); }
    else if(uEyeStyle==4){ vec2 o=f-vec2(0.,.08); d=abs(length(o)-.1)-.024; d=max(d,o.y+.035); }
    c=mix(dark,c,smoothstep(0.,aa,d));
    /* brows */
    float s=i==0?-1.:1.; vec2 a=vec2(-.09,0.),b=vec2(.09,0.); float by=uEyeRad+.11;
    if(uBrow==1){ a=vec2(-.09,by); b=vec2(.09,by+.03); }
    else if(uBrow==2){ a=vec2(-.09,by); b=vec2(.09,by+.06); }
    else if(uBrow==3){ a=vec2(-.09,by+(i==0?.07:0.)); b=vec2(.09,by+(i==0?.09:.0)); }
    if(uBrow>0){ a.x*=-s; b.x*=-s; float bd=seg2(f,a,b)-.022; c=mix(dark,c,smoothstep(0.,aa,bd)); }
    /* tears */
    if(uTears>.5){ float td=seg2(f,vec2(s*.03,-.1),vec2(s*.08,-.5))-.035; c=mix(vec3(.55,.82,1.),c,smoothstep(0.,aa,td)); }
  }
  /* mouth */
  vec2 f=q.xy-uFace.xy; float d=1.; vec3 m=dark;
  if(uMouth==0){ vec2 o=f-vec2(0.,.13); d=abs(length(o)-.16)-.024; d=max(d,o.y+.085); }
  else if(uMouth==1){ vec2 o=f-vec2(0.,.03); d=max(length(o*vec2(1.,1.1))-.17,o.y);
    float tg=length((f-vec2(0.,-.12))*vec2(1.,1.5))-.09; m=mix(tongue,dark,smoothstep(0.,aa,tg)); m=mix(vec3(1.),m,smoothstep(0.,aa,-(o.y+.04))); }
  else if(uMouth==2){ d=length((f-vec2(0.,-.03))*vec2(1.,.78))-.065; }
  else if(uMouth==3){ vec2 o=f-vec2(0.,-.17); d=abs(length(o)-.15)-.024; d=max(d,-(o.y-.09)); }
  else if(uMouth==4){ vec2 o=f-vec2(0.,-.12); d=max(length(o*vec2(1.,1.15))-.15,-o.y); float tg=length((f-vec2(0.,-.08))*vec2(1.,1.8))-.07; m=mix(tongue,dark,smoothstep(0.,aa,tg)); }
  else if(uMouth==5){ d=seg2(f,vec2(-.08,-.02),vec2(.08,-.02))-.022; }
  else if(uMouth==6){ float h=.025+.075*uTalk; vec2 o=(f-vec2(0.,-.02))/vec2(.09,h); d=(length(o)-1.)*min(.09,h); float tg=length((f-vec2(0.,-.02-h*.55))*vec2(1.,2.))-.06; m=mix(tongue,dark,smoothstep(0.,aa,tg)); }
  else if(uMouth==7){ vec2 g=r2(-.3)*(f-vec2(.03,0.)); vec2 o=g-vec2(0.,.13); d=abs(length(o)-.15)-.022; d=max(d,o.y+.1); }
  return mix(m,c,smoothstep(0.,aa,d));
}

vec3 matCol(float id,vec3 p,vec3 q,vec3 n,out float gl,out vec3 em){
  gl=.55; em=vec3(0.);
  if(id<1.5){ vec3 c=uCol*mix(.9,1.06,smoothstep(uBC.y-.9,uBC.y+.9,q.y)); return paintFace(q,c); }
  if(id<3.5){ vec3 e=id<2.5?uEyeL:uEyeR; vec3 o=normalize(q-e); vec3 lk=normalize(uLook-e); float k=dot(o,lk);
    vec3 c=vec3(.98,.98,1.); c=mix(c,uIris*.35,smoothstep(.46,.48,k)); c=mix(c,uIris,smoothstep(.5,.7,k)*.85); c=mix(c,vec3(.015,.01,.02),smoothstep(.74,.76,k));
    em=vec3(1.)*smoothstep(.962,.972,dot(o,normalize(vec3(-.35,.45,.85))))*1.3+vec3(.7)*smoothstep(.992,.995,dot(o,normalize(vec3(.25,-.2,1.))));
    float side=id<2.5?1.:-1.; float cl=id<2.5?uLid.x:uLid.y; float line=e.y+uEyeRad*(1.-2.*cl)+uLid.z*(q.x-e.x)*side;
    float lid=smoothstep(line-.004,line+.004,q.y); c=mix(c,uCol*.95,lid); em*=1.-lid; c=mix(c,vec3(.12,.06,.06),(1.-lid)*smoothstep(.02,0.,abs(q.y-line))*step(.02,cl+.02));
    gl=lid>.5?.55:.98; return c; }
  if(id<4.5) return uFoot;
  if(id<5.5) return uAccA;
  if(id<6.5) return uAccB;
  if(id<7.5){ gl=1.; return vec3(1.,.72,.2); }
  if(id<8.5) return vec3(.97,.96,.94);
  if(id<9.5){ gl=.8; return vec3(.12,.12,.16); }
  if(id<10.5){ em=vec3(1.,.82,.3)*.9; return vec3(1.,.85,.4); }
  if(id<11.5){ gl=1.; em=vec3(.1,.2,.35); return vec3(.5,.78,1.); }
  if(id<12.5) return uPA;
  if(id<13.5) return uPB;
  if(id<14.5) return uPC;
  if(id<15.5) return vec3(1.,.55,.7);
  if(id<16.5){ gl=1.; em=vec3(.08,.12,.16); return vec3(.75,.9,1.); }
  if(id<17.5){ gl=.85; return vec3(.95,.22,.3); }
  if(id<18.5) return vec3(.35,.8,.38);
  if(id<19.5){ em=uAccA*.6; return uAccA; }
  if(id<20.5){ float a=atan(q.z,q.x); return mix(uAccA,uAccB,step(.5,fract(q.y*6.+a*.5))); }
  if(id<22.5) return vec3(.72,.77,.86);
  if(id<23.5){ gl=.95; return vec3(.72,.74,.8); }
  if(id<24.5) return vec3(.86,.6,.36);
  if(id<25.5){ em=vec3(.25,.7,1.)*.8; return vec3(.3,.7,1.); }
  if(id<26.5){ gl=1.; em=vec3(.2,.8,.4)*.5; return vec3(.35,.95,.55); }
  vec3 oc=id<30.5?uOC0:id<31.5?uOC1:id<32.5?uOC2:uOC3; gl=.95; em=oc*.18; return oc;
}

void main(){
  vec2 uv=(gl_FragCoord.xy-uOff-.5*uRes)/uRes.y*2.;
  vec3 ro=uCamPos; vec3 fw=normalize(uCamTgt-ro); vec3 rt=normalize(cross(fw,vec3(0.,1.,0.))); vec3 up=cross(rt,fw);
  vec3 rd=normalize(fw+uv.x*uTanF*rt+uv.y*uTanF*up);
  /* bounding sphere */
  vec3 bc=vec3(0.,1.25,0.); float br=2.3; vec3 oc=ro-bc; float b=dot(oc,rd); float c=dot(oc,oc)-br*br; float h=b*b-c;
  vec4 outc=vec4(0.);
  float pix=2.*uTanF/uRes.y;
  float tg=-ro.y/rd.y;
  if(h>0.){
    h=sqrt(h); float t=max(-b-h,0.); float tmax=-b+h; float best=1e5; float tb=t; bool hit=false;
    for(int i=ZERO;i<110;i++){ vec3 p=ro+rd*t; float d=map(p).x; float ratio=d/t; if(ratio<best){best=ratio;tb=t;} if(d<.0007*t){hit=true;break;} t+=d*.92; if(t>tmax) break; }
    float cov=hit?1.:1.-clamp(best/pix,0.,1.);
    if(cov>0.){
      float tt=hit?t:tb; vec3 p=ro+rd*tt; vec2 mm=map(p); vec3 n=calcN(p); vec3 q=uRot*(p-uPos)+vec3(0.,1.,0.);
      float gl; vec3 em; vec3 alb=matCol(mm.y,p,q,n,gl,em);
      alb=pow(alb,vec3(2.2));
      float ao=calcAO(p,n);
      vec3 L=normalize(vec3(-.55,.78,.62)); vec3 L2=normalize(vec3(.8,.25,.35)); vec3 L3=normalize(vec3(.4,.6,-.8));
      float dif=clamp(dot(n,L)*.8+.2,0.,1.); float dif2=clamp(dot(n,L2),0.,1.); float rim=pow(clamp(dot(n,L3),0.,1.),2.);
      vec3 sky=mix(vec3(.55,.48,.52),vec3(1.,.99,1.04),n.y*.5+.5);
      vec3 col=alb*(sky*.42*ao+dif*vec3(1.06,1.,.94)*1.05+dif2*vec3(.55,.65,.85)*.28);
      col+=alb*.25*smoothstep(0.,.35,dif)*(1.-dif)*vec3(1.,.55,.45);
      col+=alb*rim*.55*ao;
      vec3 hv=normalize(L-rd); float sp=pow(clamp(dot(n,hv),0.,1.),20.+gl*90.)*gl*.85*ao;
      float fr=pow(1.-clamp(dot(n,-rd),0.,1.),4.)*.28*ao;
      col+=sp*mix(vec3(1.),alb*2.,step(6.5,mm.y)*step(mm.y,7.5))+fr*vec3(1.,.96,1.);
      col+=pow(em,vec3(2.2))*1.6+em*.25;
      col=col/(1.+col*.12);
      col=pow(col,vec3(1./2.2));
      outc=vec4(col*cov,cov);
    }
  }
  if(outc.a<.999&&tg>0.){
    vec3 g=ro+rd*tg; vec2 s=(g.xz-vec2(uPos.x,0.))/vec2(.95,.55);
    float sh=uShadow*exp(-dot(s,s)*2.2)*.42;
    outc=outc+vec4(vec3(0.),sh)*(1.-outc.a);
  }
  gl_FragColor=outc;
}`;

  /* ------------------------------------------------------------------ math */
  const V = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
    mul: (a, s) => [a[0] * s, a[1] * s, a[2] * s],
    dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
    len: a => Math.hypot(a[0], a[1], a[2]),
    norm: a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; },
    lerp: (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
  };
  function rotMat(yaw, roll, pitch) { // char -> world rotation, row-major 3x3
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cr = Math.cos(roll), sr = Math.sin(roll), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], Rz = [[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], Rx = [[1, 0, 0], [0, cp, -sp], [0, sp, cp]];
    const m = (A, B) => A.map((r, i) => [0, 1, 2].map(j => r[0] * B[0][j] + r[1] * B[1][j] + r[2] * B[2][j]));
    return m(m(Ry, Rz), Rx);
  }
  const apply = (M, v) => [M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2], M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2], M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2]];
  const transpose = M => [[M[0][0], M[1][0], M[2][0]], [M[0][1], M[1][1], M[2][1]], [M[0][2], M[1][2], M[2][2]]];
  // GLSL mat3 is column-major: q = uRot * v  must equal Minv · v (row-major Minv) -> upload Minv's columns = rows of transpose(Minv) = M (char->world) rows.
  const colMajor = M => new Float32Array([M[0][0], M[1][0], M[2][0], M[0][1], M[1][1], M[2][1], M[0][2], M[1][2], M[2][2]]);
  const HEX = new Map();
  function hex(h) { let c = HEX.get(h); if (!c) { const n = parseInt(h.slice(1), 16); c = [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]; HEX.set(h, c); } return c; }
  function ik(S, T, a, b, pole) {
    let D = V.sub(T, S); let d = V.len(D);
    const dc = Math.min(Math.max(d, Math.abs(a - b) + 1e-3), a + b - 1e-3);
    const dir = V.mul(D, 1 / (d || 1));
    const x = (a * a - b * b + dc * dc) / (2 * dc);
    const h = Math.sqrt(Math.max(a * a - x * x, 0));
    let perp = V.sub(pole, V.mul(dir, V.dot(pole, dir)));
    perp = V.norm(perp);
    const E = V.add(V.add(S, V.mul(dir, x)), V.mul(perp, h));
    const H = V.add(S, V.mul(dir, dc));
    return [E, H];
  }
  const smooth = t => t * t * (3 - 2 * t);

  /* ------------------------------------------------------------------ bodies */
  const BODIES = [
    { c: [0, 1.13, 0], r: [0.78, 0.8, 0.74], sh: [0.6, 0.98], ey: 1.25, ex: 0.27, fy: 0.97, top: 1.92, hip: 0.27, bot: 0.33 },
    { c: [0, 1.22, 0], r: [0.64, 0.22, 0.64], sh: [0.54, 1.02], ey: 1.34, ex: 0.25, fy: 1.08, top: 2.06, hip: 0.26, bot: 0.36 },
    { c: [0, 1.14, 0], r: [0.5, 0.5, 0.44], sh: [0.62, 0.98], ey: 1.24, ex: 0.27, fy: 0.98, top: 1.9, hip: 0.28, bot: 0.37 },
    { c: [0, 1.02, 0], r: [0.74, 0.88, 0.1], sh: [0.58, 0.94], ey: 1.12, ex: 0.26, fy: 0.87, top: 1.98, hip: 0.26, bot: 0.28 },
    { c: [0, 1.0, 0], r: [0.92, 0.66, 0.78], sh: [0.74, 0.9], ey: 1.1, ex: 0.3, fy: 0.86, top: 1.65, hip: 0.3, bot: 0.34 }
  ];
  function bodyZ(type, B, x, y) { // front surface z (approximate, ellipsoid-like fit)
    const b = BODIES[type];
    if (type === 1) { const dy = Math.max(0, Math.abs(y - B.c[1]) - B.r[1]); const r2 = B.r[0] * B.r[0] - dy * dy - x * x; return Math.sqrt(Math.max(r2, 0.01)); }
    if (type === 2) { const ex = B.r[0] + 0.27, ey = B.r[1] + 0.27, ez = B.r[2] + 0.27; const k = 1 - Math.pow(Math.abs(x) / ex, 4) - Math.pow(Math.abs(y - B.c[1]) / ey, 4); return ez * Math.pow(Math.max(k, 0.01), 0.25); }
    if (type === 3) { const r = B.r[0] * (1 - Math.max(0, y - B.c[1]) / (B.r[1] * 1.15)); const r2 = r * r - x * x - Math.pow(Math.min(0, y - B.c[1]), 2); return Math.sqrt(Math.max(r2, 0.01)); }
    const k = 1 - Math.pow(x / B.r[0], 2) - Math.pow((y - B.c[1]) / B.r[1], 2); return B.r[2] * Math.sqrt(Math.max(k, 0.01));
  }

  /* ------------------------------------------------------------------ motions
     Each returns hand targets (char space), feet, and body motion. Character space: feet on y=0,
     +z faces the viewer, +x is the character's left on screen (viewer's right). */
  const P = {
    rest: s => [s * 0.92, 0.5, 0.16],
  };
  const MOTIONS = {
    idle(t) { return { L: [-0.92, 0.5 + 0.02 * Math.sin(t * 1.4), 0.16 + 0.05 * Math.sin(t)], R: [0.92, 0.5 + 0.02 * Math.sin(t * 1.4 + 1), 0.16 - 0.05 * Math.sin(t)], hop: 0.025 * (1 - Math.cos(t * 2.4)), yaw: 0.38 * Math.sin(t * 0.55) }; },
    wave(t) { return { L: [-0.92, 0.52, 0.16], R: [0.98 + 0.16 * Math.sin(t * 7), 1.72, 0.3], hop: 0.03 * (1 - Math.cos(t * 3.5)), yaw: 0.3 * Math.sin(t * 0.6) - 0.1, roll: -0.05 }; },
    point(t) { return { L: [-0.9, 0.52, 0.2], R: [0.62, 1.98 + 0.06 * Math.sin(t * 4), 0.35], hop: Math.abs(Math.sin(t * 2.2)) * 0.08, yaw: 0.25 * Math.sin(t * 0.7), look: 'prop', prop: 'R' }; },
    cheer(t) { const b = Math.abs(Math.sin(t * 4.6)); return { L: [-0.86, 1.82 + 0.12 * Math.sin(t * 9.2), 0.22], R: [0.86, 1.82 + 0.12 * Math.sin(t * 9.2 + 1.5), 0.22], hop: b * 0.3, squash: 1 - b, yaw: 0.25 * Math.sin(t * 1.2) }; },
    champion(t) {
      const c = t % 3.6; const flip = c > 1.6 && c < 2.6 ? smooth((c - 1.6) / 1) : c >= 2.6 ? 1 : 0;
      const b = Math.abs(Math.sin(t * 4.6));
      return { L: [-0.86, 1.8 + 0.1 * Math.sin(t * 9), 0.22], R: [0.86, 1.8 + 0.1 * Math.sin(t * 9 + 1.5), 0.25], hop: c > 1.6 && c < 2.6 ? Math.sin(flip * Math.PI) * 0.45 : b * 0.2, pitch: -flip * Math.PI * 2, squash: c > 1.6 && c < 2.6 ? 0 : 1 - b, yaw: 0.3 * Math.sin(t * 0.9), prop: 'R' };
    },
    cry(t) { const j = 0.025 * Math.sin(t * 22); return { L: [-0.27 + j, 1.13, 0.86], R: [0.27 - j, 1.13, 0.86], hop: 0, yaw: 0.12 * Math.sin(t * 0.8), roll: 0.03 * Math.sin(t * 11), squash: 0.25 + 0.1 * Math.sin(t * 11) }; },
    think(t) { return { L: [-0.32, 0.62, 0.82], R: [0.2, 0.74 + 0.02 * Math.sin(t * 3), 0.88], hop: 0.02 * (1 - Math.cos(t * 2)), yaw: -0.25 + 0.12 * Math.sin(t * 0.6), roll: 0.12, look: 'up' }; },
    read(t) { return { L: [-0.34, 0.6, 0.9], R: [0.34, 0.6, 0.9], prop: 'C', propAt: [0, 0.66, 1.02], hop: 0.02 * (1 - Math.cos(t * 2)), yaw: 0.22 * Math.sin(t * 0.5), look: 'prop' }; },
    write(t) { return { L: [-0.3, 0.68, 0.88], R: [0.1 + 0.06 * Math.sin(t * 9), 0.72 + 0.04 * Math.cos(t * 9), 1.0], prop: 'R', hop: 0, yaw: 0.18 * Math.sin(t * 0.5), roll: 0.04, look: 'prop' }; },
    type(t) { return { L: [-0.28, 0.52 + 0.04 * Math.max(0, Math.sin(t * 13)), 0.9], R: [0.28, 0.52 + 0.04 * Math.max(0, Math.sin(t * 13 + 2)), 0.9], prop: 'C', propAt: [0, 0.42, 0.95], hop: 0, yaw: 0.15 * Math.sin(t * 0.5), look: 'prop' }; },
    present(t) { return { L: [-0.72, 0.58, 0.32], R: [1.18, 1.22 + 0.06 * Math.sin(t * 2.4), 0.36], prop: 'R', hop: 0.02 * (1 - Math.cos(t * 2.4)), yaw: -0.2 + 0.18 * Math.sin(t * 0.6), roll: 0.04 }; },
    listen(t) { return { L: [-0.92, 0.52, 0.2], R: [0.84, 1.28, 0.26], hop: 0.02 * (1 - Math.cos(t * 2)), yaw: 0.3 * Math.sin(t * 0.6), roll: 0.16 + 0.05 * Math.sin(t * 2.6) }; },
    talk(t) { return { L: [-0.98, 0.9 + 0.18 * Math.sin(t * 3), 0.4], R: [0.2, 0.74, 0.92], prop: 'R', talk: 1, hop: 0.02 * (1 - Math.cos(t * 3)), yaw: 0.25 * Math.sin(t * 0.7), roll: 0.05 * Math.sin(t * 1.6) }; },
    shrug(t) { const k = Math.sin(t * 3) * 0.5 + 0.5; return { L: [-1.0, 0.82 + 0.1 * k, 0.4], R: [1.0, 0.82 + 0.1 * k, 0.4], hop: 0.04 * k, yaw: 0.2 * Math.sin(t * 0.8), roll: 0.08 * Math.sin(t * 1.5) }; },
    hug(t) { const k = smooth(Math.sin(t * 1.6) * 0.5 + 0.5); return { L: V.lerp([-1.12, 1.05, 0.4], [-0.34, 0.9, 0.9], k), R: V.lerp([1.12, 1.05, 0.4], [0.34, 0.9, 0.9], k), prop: 'C', propAt: [0, 0.95, 1.05], hop: 0.03 * k, yaw: 0.2 * Math.sin(t * 0.6) }; },
    walk(t) { const s = Math.sin(t * 5.2); return { L: [-0.9, 0.55, 0.16 - s * 0.3], R: [0.82, 0.72, 0.48 + s * 0.15], prop: 'R', FL: [-0.29, 0.08 + Math.max(0, s) * 0.12, 0.08 + s * 0.2], FR: [0.29, 0.08 + Math.max(0, -s) * 0.12, 0.08 - s * 0.2], hop: Math.abs(Math.sin(t * 5.2)) * 0.06, yaw: 0.35 * Math.sin(t * 0.5), roll: 0.04 * s }; },
    float(t) { return { L: [-1.05, 0.95 + 0.08 * Math.sin(t * 1.5), 0.1], R: [1.05, 0.95 + 0.08 * Math.sin(t * 1.5 + 1), 0.1], hop: 0.2 + 0.12 * Math.sin(t * 1.5), yaw: 0.45 * Math.sin(t * 0.4), roll: 0.06 * Math.sin(t * 0.8), FL: [-0.25, 0.14, 0.15], FR: [0.25, 0.1, 0.18] }; },
    dance(t) { const s = Math.sin(t * 4); return { L: [-0.86, s > 0 ? 1.8 : 0.7, 0.3], R: [0.86, s > 0 ? 0.7 : 1.8, 0.3], hop: Math.abs(Math.sin(t * 8)) * 0.14, yaw: 0.5 * Math.sin(t * 2), roll: 0.12 * s, prop: 'R' }; },
    strut(t) { const s = Math.sin(t * 5); return { L: [-0.9, 0.5, 0.2], R: [0.72, 1.0 + 0.04 * s, 0.6], prop: 'R', hop: Math.abs(s) * 0.05, yaw: 0.3 * Math.sin(t * 0.8), roll: 0.08 * s }; },
    ring(t) { return { L: [-0.9, 0.52, 0.2], R: [0.82, 1.28, 0.42], prop: 'R', hop: Math.abs(Math.sin(t * 3)) * 0.05, yaw: 0.3 * Math.sin(t * 0.7) }; },
    guard(t) { return { L: [-0.92, 0.55, 0.2], R: [0.3, 0.82, 0.98], prop: 'R', hop: 0.08 + 0.06 * Math.sin(t * 1.6), yaw: 0.25 * Math.sin(t * 0.5) }; },
    flip(t) { const k = Math.min(1, (t % 1.2) / 0.9); const f = smooth(k); return { L: [-0.85, 1.75, 0.2], R: [0.85, 1.75, 0.2], hop: Math.sin(f * Math.PI) * 0.42, pitch: -f * Math.PI * 2, yaw: 0 }; }
  };

  /* ------------------------------------------------------------------ registry */
  const PROPS = { none: 0, bulb: 1, key: 2, compass: 3, book: 4, pencil: 5, magnifier: 6, mic: 7, clock: 8, laptop: 9, chart: 10, bell: 11, shield: 12, envelope: 13, pointer: 14, heart: 15, trophy: 16, clipboard: 17, flask: 18 };
  const ACCS = { none: 0, sprout: 1, gradcap: 2, glasses: 3, headphones: 4, crown: 5, halo: 6, antenna: 7, partyhat: 8, cap: 9, beanie: 10, bow: 11, beret: 12, raincloud: 13 };
  const ORBS = { orb: 0, star: 1, ring: 2, cube: 3, heart: 4, check: 5, gem: 6 };
  const PROP_ROT = { pencil: [0, 0.6, 0.5], pointer: [0, -0.25, -0.9], mic: [0, 0, 0.35], magnifier: [0, -0.2, -0.3], key: [0, 0, -0.4], bulb: [0, 0, 0], compass: [0.25, 0, 0], clock: [0, 0, 0], bell: [0, 0, 0], shield: [0, 0, 0], envelope: [0, 0, 0.1], heart: [0, 0, 0], trophy: [0, 0, 0], clipboard: [0, 0, 0], flask: [0, 0, 0], chart: [0.2, 0, 0], book: [-0.35, 0, 0], laptop: [0, 0, 0] };
  const PROP_OFF = { pencil: [0.02, 0.02, 0.06], pointer: [0, 0.02, 0.05], mic: [0, 0.18, 0.06], magnifier: [0.02, 0.15, 0.08], key: [0, 0.15, 0.08], bulb: [0, 0.16, 0.05], compass: [0, 0.12, 0.12], clock: [0, 0.18, 0.1], bell: [0, 0.16, 0.1], shield: [0, 0.12, 0.14], envelope: [0, 0.14, 0.12], heart: [0, 0.12, 0.12], trophy: [0, 0.14, 0.1], clipboard: [-0.02, 0.18, 0.1], flask: [0, 0.18, 0.08], chart: [0, 0.12, 0.12], book: [0, 0, 0], laptop: [0, 0, 0] };

  /* ------------------------------------------------------------------ GL
     Performance notes (v0.9.2). The previous renderer could freeze the whole browser:
     1. It compiled the shader synchronously while the first screen was being drawn. Where
        KHR_parallel_shader_compile is missing (Firefox, many Chrome/Edge GPU configurations)
        that single call blocked the page for seconds (14 s measured on a software GPU).
     2. Every frame it copied the WebGL canvas into each character's 2D canvas. Chrome turns
        that into a synchronous GPU read-back ("GPU stall due to ReadPixels"), once per
        character, at up to 45 fps.
     3. Nothing limited queued GPU work. A slow GPU kept accepting new frames, and because
        Chrome and Edge share one GPU process across all tabs, the browser itself stopped
        responding. The stall guard only measured CPU time, so it never noticed.
     4. Software WebGL (SwiftShader / llvmpipe / "Microsoft Basic Render Driver") ray-marched
        on the CPU across every core.
     Now: the context is probed cheaply, software renderers use the emoji fallback, the program
     compiles after the first paint (in parallel where supported, as WebGL2 with loops that
     drivers cannot unroll), all characters render into one atlas per frame, frames reach the
     page as ImageBitmaps (no read-back), at most one GPU frame is in flight (WebGL2 fences),
     and quality/frame rate adapt to measured GPU latency. */
  const MODE = (function () {
    try { const m = (new URLSearchParams(location.search).get('cp3d') || localStorage.getItem('cp3d') || '').toLowerCase(); if (m === 'reset') localStorage.removeItem('cp3d-guard'); return m; } catch (e) { return ''; }
  })(); // 'off' = always emoji, 'force' = render even on a software GPU (testing only)
  const SOFTWARE = /swiftshader|llvmpipe|softpipe|software|basic render|lavapipe|mesa offscreen/i;
  let gl = null, gl2 = false, glCanvas = null, prog = null, vsh = null, fsh = null, loc = {}, parallel = null;
  let softGL = false, probed = false, failed = false, lost = false, ready = false, compiling = false, lostTimer = 0;
  const stats = { gl2: false, renderer: '', compileMs: 0, quality: 1, fps: 0, gpuMs: 0, frames: 0, reason: '' };

  /* v0.9.3 safety memory (per device + renderer + version). 'starting' is written before the
     first 3D start and replaced by 'ok' once a real frame is confirmed. If the page froze or was
     closed/refreshed before that, the leftover 'starting' means this device should use emoji,
     so a refresh can never freeze the browser again. ?cp3d=reset clears it. */
  const GUARD_KEY = 'cp3d-guard', GUARD_V = '0.9.4';
  function guardGet() { try { return JSON.parse(localStorage.getItem(GUARD_KEY) || 'null'); } catch (e) { return null; } }
  function guardSet(state) { try { const g = guardGet() || {}; localStorage.setItem(GUARD_KEY, JSON.stringify({ v: GUARD_V, r: stats.renderer, state: state, strikes: state === 'ok' ? 0 : (g.strikes || 0), wasOk: state === 'ok' || !!(g.wasOk && g.r === stats.renderer), t: Date.now() })); } catch (e) {} }
  function guardBlocks() {
    if (MODE === 'reset') { try { localStorage.removeItem(GUARD_KEY); } catch (e) {} return false; }
    const g = guardGet();
    if (!g || g.v !== GUARD_V || g.r !== stats.renderer) return false;
    if (Date.now() - (g.t || 0) > 7 * 864e5) return false;          // retry after a week (driver updates)
    if (g.state === 'bad') return true;
    if (g.state === 'starting') {                                  // previous start never confirmed a frame
      const strikes = (g.strikes || 0) + 1;
      try { localStorage.setItem(GUARD_KEY, JSON.stringify(Object.assign(g, { strikes: strikes, state: strikes >= 2 ? 'bad' : 'starting' }))); } catch (e) {}
      return strikes >= 2;
    }
    return false;
  }
  function probe() {
    if (probed) return !!gl;
    probed = true;
    try {
      if (MODE !== 'live' && MODE !== 'force' && MODE !== 'guardtest') throw new Error('live 3D is opt-in (?cp3d=live); showing the pre-rendered 3D characters');
      glCanvas = document.createElement('canvas');
      glCanvas.width = 512; glCanvas.height = 256;
      const attrs = { premultipliedAlpha: true, alpha: true, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: false, powerPreference: 'low-power', failIfMajorPerformanceCaveat: false };
      gl = glCanvas.getContext('webgl2', attrs); gl2 = !!gl;
      if (!gl) gl = glCanvas.getContext('webgl', attrs) || glCanvas.getContext('experimental-webgl', attrs);
      if (!gl) throw new Error('no hardware WebGL');
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      stats.renderer = String((dbg && gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) || gl.getParameter(gl.RENDERER) || '');
      softGL = SOFTWARE.test(stats.renderer); // v0.9.4: software graphics still get 3D, in a light profile
      if (MODE !== 'force' && guardBlocks()) throw new Error('3D was turned off on this device after an earlier start froze or failed (add ?cp3d=reset to retry)');
      stats.gl2 = gl2; stats.software = softGL;
      if (softGL) document.documentElement.classList.add('cp-lite'); // lighter CSS effects too
      glCanvas.addEventListener('webglcontextlost', onLost, false);
      glCanvas.addEventListener('webglcontextrestored', onRestored, false);
      return true;
    } catch (err) {
      fail(err, true);
      return false;
    }
  }
  function fail(err, quiet) {
    if (!quiet && stats.renderer) guardSet('bad');
    failed = true; ready = false; stats.reason = (err && err.message) || String(err);
    if (gl) { const ext = gl.getExtension('WEBGL_lose_context'); gl = null; try { if (ext) ext.loseContext(); } catch (e) {} }
    if (window.console) console[quiet ? 'info' : 'warn']('CP3D: using emoji characters (' + stats.reason + ').');
    window.dispatchEvent(new Event('cp3d-lost'));
  }
  function onLost(e) {
    if (failed) return;
    e.preventDefault(); lost = true; ready = false; compiling = false; prog = null; loc = {};
    clearTimeout(lostTimer);
    lostTimer = setTimeout(function () { if (lost) fail(new Error('GPU context was not restored')); }, 5000);
  }
  function onRestored() { if (failed) return; lost = false; clearTimeout(lostTimer); pending = null; startCompile(); }

  function sources() {
    const hp = gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT);
    let fs = hp && hp.precision > 0 ? FS : FS.replace('precision highp float;', 'precision mediump float;');
    if (gl2) {
      fs = '#version 300 es\n' + fs.replace(/(precision \w+ float;)/, '$1\nout vec4 fragColor;\nuniform int uZero;\n#define ZERO uZero').replace('gl_FragColor=', 'fragColor=');
      return ['#version 300 es\nin vec2 a;void main(){gl_Position=vec4(a,0.,1.);}', fs];
    }
    return [VS, fs.replace(/(precision \w+ float;)/, '$1\n#define ZERO 0')];
  }
  function startCompile() {
    if (!gl || compiling || ready || failed || lost) return;
    compiling = true;
    afterPaint(function () {
      if (!gl || failed || lost) { compiling = false; return; }
      try {
        if (MODE !== 'force') guardSet('starting');
        const t0 = performance.now();
        const src = sources();
        parallel = gl.getExtension('KHR_parallel_shader_compile');
        const sh = function (type, text) { const s = gl.createShader(type); gl.shaderSource(s, text); gl.compileShader(s); return s; };
        prog = gl.createProgram();
        vsh = sh(gl.VERTEX_SHADER, src[0]); fsh = sh(gl.FRAGMENT_SHADER, src[1]);
        gl.attachShader(prog, vsh); gl.attachShader(prog, fsh);
        gl.linkProgram(prog);
        stats.compileStart = t0;
        if (!parallel) finishProgram();
        schedule();
      } catch (err) { compiling = false; fail(err); }
    });
  }
  function finishProgram() {
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      const log = (gl.getShaderInfoLog(vsh) || '') + (gl.getShaderInfoLog(fsh) || '') + (gl.getProgramInfoLog(prog) || '');
      throw new Error(log || 'shader link failed');
    }
    gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const a = gl.getAttribLocation(prog, 'a'); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0);
    loc = {};
    const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const u = gl.getActiveUniform(prog, i); const name = u.name.replace(/\[0\]$/, ''); loc[name] = gl.getUniformLocation(prog, u.name); }
    if (loc.uZero) gl.uniform1i(loc.uZero, 0);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND);
    stats.compileMs = Math.round(performance.now() - stats.compileStart);
    ready = true; compiling = false;
    if (stats.compileMs > 4000 && MODE !== 'force') throw new Error('3D setup took ' + stats.compileMs + ' ms on this device');
  }
  /* Run after the browser has painted the current screen and is idle (bounded delay). */
  function afterPaint(fn) {
    requestAnimationFrame(function () {
      setTimeout(function () {
        if ('requestIdleCallback' in window) requestIdleCallback(fn, { timeout: 700 }); else setTimeout(fn, 60);
      }, 0);
    });
  }
  const u3 = (n, v) => { if (loc[n]) gl.uniform3f(loc[n], v[0], v[1], v[2]); };
  const u1 = (n, v) => { if (loc[n]) gl.uniform1f(loc[n], v); };
  const ui = (n, v) => { if (loc[n]) gl.uniform1i(loc[n], v); };
  const ORB_BUF = new Float32Array(16);

  /* ------------------------------------------------------------------ one character frame */
  const CAM = { pos: [0, 1.2, 5.6], tgt: [0, 1.16, 0], tan: 0.245 };
  function frameCharacter(ch, now) {
    const spec = ch.spec, face = ch.face;
    const t = now * (ch.speed || 1) + ch.seed;
    const mot = (MOTIONS[ch.motion] || MOTIONS.idle)(t);
    const type = spec.body || 0;
    const base = BODIES[type];
    // boxy / wide bodies stick out further in front: push front-of-body hand poses forward
    const zf = type === 2 ? 0.16 : type === 4 ? 0.07 : type === 1 ? 0.03 : 0;
    if (zf) ['L', 'R', 'propAt'].forEach(function (k) { if (mot[k] && mot[k][2] > 0.55) mot[k] = [mot[k][0], mot[k][1], mot[k][2] + zf]; });
    // squash & stretch
    const sq = mot.squash ? mot.squash * 0.07 : 0;
    const sy = 1 - sq, sx = 1 + sq * 0.6;
    const B = { c: [0, base.bot + (base.c[1] - base.bot) * sy, 0], r: type === 1 ? [base.r[0] * sx, base.r[1] * sy, base.r[2]] : type === 3 ? [base.r[0] * sx, base.r[1] * sy, base.r[2]] : [base.r[0] * sx, base.r[1] * sy, base.r[2] * sx] };
    const yOf = y => base.bot + (y - base.bot) * sy;
    const shz = type === 2 ? 0.3 : type === 4 ? 0.12 : 0;
    const SL = [-base.sh[0] * sx, yOf(base.sh[1]), shz], SR = [base.sh[0] * sx, yOf(base.sh[1]), shz];
    const ey = yOf(base.ey), ex = (base.ex + 0.02) * sx, er = spec.eye || 0.165;
    const eyeL = [-ex, ey, bodyZ(type, B, ex, ey) - er * 0.42], eyeR = [ex, ey, eyeL[2]];
    const fy = yOf(base.fy);
    const faceP = [0, fy, bodyZ(type, B, 0, fy)];
    const top = [0, yOf(base.top) - 0.03, 0];
    // arms (IK). Poles keep elbows out and slightly back.
    const [EL, HL] = ik(SL, mot.L, 0.32, 0.31, [-0.7, -0.5, -0.5]);
    const [ER, HR] = ik(SR, mot.R, 0.32, 0.31, [0.7, -0.5, -0.5]);
    const hipY = base.bot + 0.12;
    const HipL = [-base.hip, hipY, 0.02], HipR = [base.hip, hipY, 0.02];
    const [KL, FL] = ik(HipL, mot.FL || [-base.hip - 0.02, 0.09, 0.06], 0.19, 0.19, [0, 0.2, 1]);
    const [KR, FR] = ik(HipR, mot.FR || [base.hip + 0.02, 0.09, 0.06], 0.19, 0.19, [0, 0.2, 1]);
    // whole-body transform (pivot at body centre)
    const yaw = (mot.yaw || 0) + (ch.yawBias || 0), roll = mot.roll || 0, pitch = mot.pitch || 0;
    const M = rotMat(yaw, roll, pitch); const Mi = transpose(M);
    const pivotW = [ch.x || 0, 1 + (mot.hop || 0), 0];
    const toChar = w => V.add(apply(Mi, V.sub(w, pivotW)), [0, 1, 0]);
    const toWorld = c => V.add(apply(M, V.sub(c, [0, 1, 0])), pivotW);
    // prop
    let propPos = HR, propId = PROPS[ch.prop || 'none'] || 0, prot = [0, 0, 0];
    if (propId) {
      const off = PROP_OFF[ch.prop] || [0, 0.1, 0.08];
      prot = PROP_ROT[ch.prop] || [0, 0, 0];
      if (mot.prop === 'C' || ch.prop === 'book' || ch.prop === 'laptop') propPos = mot.propAt || V.lerp(HL, HR, 0.5);
      else propPos = V.add(HR, off);
      if (ch.prop === 'book' && mot.prop !== 'C') propPos = V.add(HR, [-0.1, 0.12, 0.12]);
      if (ch.prop === 'laptop' && mot.prop !== 'C') propPos = [0, 0.42, 0.95];
    }
    // orbiters (world space; ellipse sized to stay inside the frame)
    const orbs = ch.orbs || [];
    const ow = [];
    let front = null, frontZ = -9;
    for (let i = 0; i < 4; i++) {
      if (i >= orbs.length) { ow.push([0, 0, 0, -1]); continue; }
      const a = now * 0.62 * (ch.orbSpeed || 1) + i * Math.PI * 2 / orbs.length + ch.seed;
      const p = [1.18 * Math.cos(a), 1.12 + 0.16 * Math.sin(a * 2 + i), 0.7 * Math.sin(a)];
      ow.push([p[0], p[1], p[2], ORBS[orbs[i].t] || 0]);
      if (p[2] > frontZ) { frontZ = p[2]; front = p; }
    }
    // eyes: follow the nearest orbiter, the prop, the pointer, or look up while thinking
    let target;
    if (ch.pointer) target = ch.pointer;
    else if (mot.look === 'up') target = toWorld([-0.7, 2.6, 2.2]);
    else if (mot.look === 'prop' && propId) target = toWorld(propPos);
    else if (front) target = front;
    else target = [0, 1.2, 4];
    ch.lookW = ch.lookW ? V.lerp(ch.lookW, target, 0.12) : target;
    const look = toChar(V.lerp(ch.lookW, CAM.pos, 0.38));
    // blink
    if (!ch.nextBlink || now > ch.nextBlink + 0.16) ch.nextBlink = now + 1.8 + Math.random() * 3.2;
    const blink = now > ch.nextBlink && now < ch.nextBlink + 0.16 ? Math.sin((now - ch.nextBlink) / 0.16 * Math.PI) : 0;
    const lid = face.lid || [0, 0, 0];

    u1('uTime', t);
    u3('uPos', pivotW);
    gl.uniformMatrix3fv(loc.uRot, false, colMajor(Mi));
    ui('uBody', type === 4 ? 0 : type);
    u3('uBC', B.c); u3('uBR', type === 4 ? B.r : B.r);
    u3('uCol', spec.rgb); u3('uFoot', spec.footRgb); u3('uIris', spec.irisRgb); u3('uAccA', spec.accARgb); u3('uAccB', spec.accBRgb);
    u3('uSL', SL); u3('uSR', SR); u3('uEL', EL); u3('uER', ER); u3('uHL', HL); u3('uHR', HR);
    u3('uHipL', HipL); u3('uHipR', HipR); u3('uKL', KL); u3('uKR', KR); u3('uFL', FL); u3('uFR', FR);
    u3('uEyeL', eyeL); u3('uEyeR', eyeR); u1('uEyeRad', er); u3('uLook', look);
    u3('uLid', [Math.max(lid[0], blink), Math.max(lid[1], blink), lid[2]]);
    ui('uEyeStyle', face.eyes || 0); ui('uMouth', mot.talk ? 6 : (face.mouth || 0)); ui('uBrow', face.brow || 0);
    u1('uTalk', 0.5 + 0.5 * Math.sin(t * 17) * Math.sin(t * 5.3)); u1('uBlush', face.blush === undefined ? (spec.blush ? 1 : 0) : face.blush); u1('uTears', face.tears ? 1 : 0);
    u3('uFace', faceP); u3('uTop', top);
    ui('uAcc1', ACCS[(ch.acc || spec.acc || [])[0]] || 0); ui('uAcc2', ACCS[(ch.acc || spec.acc || [])[1]] || 0);
    ui('uProp', propId); u3('uPP', propPos);
    gl.uniformMatrix3fv(loc.uPR, false, colMajor(transpose(rotMat(prot[1], prot[2], prot[0]))));
    const pc = ch.propColors || spec.propColors || ['#ff6b6b', '#4dabf7', '#51cf66'];
    u3('uPA', hex(pc[0])); u3('uPB', hex(pc[1])); u3('uPC', hex(pc[2]));
    if (loc.uOrb) { for (let i = 0; i < 16; i++) ORB_BUF[i] = ow[i >> 2][i & 3]; gl.uniform4fv(loc.uOrb, ORB_BUF); }
    for (let i = 0; i < 4; i++) u3('uOC' + i, hex((orbs[i] && orbs[i].c) || '#ffffff'));
    u3('uCamPos', CAM.pos); u3('uCamTgt', CAM.tgt); u1('uTanF', CAM.tan);
    u1('uShadow', 1 - Math.min(0.7, (mot.hop || 0) * 1.4));
  }

  /* ------------------------------------------------------------------ frame loop */
  const chars = new Set();
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = window.matchMedia('(max-width: 900px), (pointer: coarse)');
  const lowEnd = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4 || !!(navigator.connection && navigator.connection.saveData);
  const maxFps = () => reduce.matches ? 18 : softGL ? 20 : mobile.matches || lowEnd ? 30 : 45;
  const DPR_CAP = 1.5;                                   // was 2: invisible on characters this size, 44% fewer pixels
  const BUDGET = () => (softGL ? 90000 : mobile.matches || lowEnd ? 260000 : 520000); // pixels shaded per frame, all characters together
  const ATLAS_W = 2048;
  let raf = 0, last = 0, quality = 0.75, fpsCap = 15, slow = 0, fast = 0, stalls = 0;
  let pending = null, pendingAt = 0, pendingWaits = 0, presenting = 0;
  const useBitmaps = typeof createImageBitmap === 'function' && typeof ImageBitmapRenderingContext !== 'undefined';
  let bitmapsOK = useBitmaps && MODE === 'bitmap'; // v0.9.3: off by default; blank on some Windows GPU drivers

  function sizeOf(ch) {
    if (!ch.cssW) { const r = ch.canvas.getBoundingClientRect(); ch.cssW = r.width; ch.cssH = r.height; }
    return [ch.cssW, ch.cssH];
  }
  function adapt(ms, keptUp) { // ms = measured GPU (or present) latency; keptUp = finished before the next display frame
    stats.gpuMs = Math.round(ms);
    const budget = 1000 / fpsCap;
    if (ms > 3000) { if (++stalls >= 3) { fail(new Error('GPU too slow for 3D characters')); return; } } else if (ms < 1000) stalls = 0;
    if (ms > budget * 1.4) {
      fast = 0;
      if (++slow >= 3) { slow = 0; if (quality > 0.45) quality = Math.max(0.4, quality - 0.15); else if (fpsCap > 10) fpsCap = Math.max(10, fpsCap - 5); }
    } else if (keptUp || ms < budget * 0.45) {
      slow = Math.max(0, slow - 1);
      if (++fast >= 45) { fast = 0; if (quality < 1) quality = Math.min(1, quality + 0.1); else if (fpsCap < maxFps()) fpsCap = Math.min(maxFps(), fpsCap + 8); }
    } else { slow = Math.max(0, slow - 1); fast = 0; }
    stats.quality = +quality.toFixed(2); stats.fps = fpsCap;
  }
  /* v0.9.3: the emoji stays until a frame is confirmed to contain the character. If a GPU
     driver produces blank frames, every character switches to emoji instead of vanishing. */
  function verify(ch, ctx, w, h) {
    let ok = false;
    try { const d = ctx.getImageData(w >> 1, (h * 0.15) | 0, 1, Math.max(1, (h * 0.7) | 0)).data; for (let i = 3; i < d.length; i += 4) if (d[i] > 8) { ok = true; break; } } catch (e) { ok = true; }
    if (ok) { shown(ch); if (++verified === 1) guardSet('ok'); return; }
    if (++ch.blank >= 4) fail(new Error('3D frames were blank on this GPU'));
  }
  let verified = 0;
  function shown(ch) {
    if (ch.shown) return;
    ch.shown = true;
    const ph = ch.canvas.parentNode && ch.canvas.parentNode.querySelector('.cp-wait');
    if (ph) { ph.classList.add('cp-gone'); setTimeout(function () { ph.remove(); }, 300); } // cross-fade from the 3D still
  }
  function drop(ch) { chars.delete(ch); if (io) io.unobserve(ch.canvas); if (ro) ro.unobserve(ch.canvas); }

  function draw(now) {
    raf = 0;
    if (!gl || failed || lost || document.hidden) return;
    if (!ready) {
      if (!compiling) { startCompile(); return; }
      if (!prog) return;                                   // compile not started yet; startCompile schedules us
      if (parallel && !gl.getProgramParameter(prog, parallel.COMPLETION_STATUS_KHR)) { schedule(); return; }
      try { finishProgram(); } catch (err) { compiling = false; fail(err); return; }
    }
    // Backpressure: never queue a new frame while the GPU is still busy with the previous one.
    if (pending) {
      const st = gl.clientWaitSync(pending, 0, 0);
      if (st === gl.TIMEOUT_EXPIRED || st === gl.WAIT_FAILED) {
        if (now - pendingAt > 6000) { fail(new Error('GPU stopped responding')); return; }
        pendingWaits++; schedule(); return;
      }
      gl.deleteSync(pending); pending = null; adapt(now - pendingAt, pendingWaits === 0);
    }
    if (presenting) { schedule(); return; }
    if (now - last < 1000 / fpsCap - 2) { schedule(); return; }
    last = now;

    // Visible characters only (IntersectionObserver), at a resolution that fits the pixel budget.
    const list = [];
    let total = 0;
    chars.forEach(function (ch) {
      if (!ch.canvas.isConnected) { drop(ch); return; }
      if (!ch.visible) return;
      const s = sizeOf(ch);
      if (s[0] < 2 || s[1] < 2) return;
      list.push(ch); total += s[0] * s[1];
    });
    if (!list.length) return;                              // sleep; observers wake the loop
    const dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
    let scale = dpr * quality;
    if (total * scale * scale > BUDGET()) scale = Math.sqrt(BUDGET() / total);
    scale = Math.max(softGL ? 0.35 : 0.5, scale);

    // Shelf-pack every character into one atlas, render them all, then present.
    let x = 0, y = 0, rowH = 0;
    const jobs = [];
    list.forEach(function (ch) {
      const w = Math.max(4, Math.min(ATLAS_W, Math.round(ch.cssW * scale))), h = Math.max(4, Math.round(ch.cssH * scale));
      if (x + w > ATLAS_W) { x = 0; y += rowH; rowH = 0; }
      jobs.push({ ch: ch, x: x, y: y, w: w, h: h });
      x += w; rowH = Math.max(rowH, h);
    });
    const needW = jobs.reduce((m, j) => Math.max(m, j.x + j.w), 0), needH = y + rowH;
    if (glCanvas.width < needW || glCanvas.height < needH) {
      glCanvas.width = Math.min(ATLAS_W, Math.max(glCanvas.width, Math.ceil(needW / 64) * 64));
      glCanvas.height = Math.max(glCanvas.height, Math.ceil(needH / 64) * 64);
    }
    const H = glCanvas.height;
    const t0 = performance.now();
    const secs = now / 1000 * (reduce.matches ? 0.35 : 1);
    gl.enable(gl.SCISSOR_TEST);
    gl.clearColor(0, 0, 0, 0);
    jobs.forEach(function (j) {
      j.gy = H - j.y - j.h;                                // GL origin is bottom-left
      gl.viewport(j.x, j.gy, j.w, j.h); gl.scissor(j.x, j.gy, j.w, j.h);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(loc.uRes, j.w, j.h);
      if (loc.uOff) gl.uniform2f(loc.uOff, j.x, j.gy);
      frameCharacter(j.ch, secs);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    });
    gl.disable(gl.SCISSOR_TEST);
    if (gl2) { pending = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0); pendingAt = performance.now(); pendingWaits = 0; }
    gl.flush();
    stats.frames++;

    if (bitmapsOK) {
      // Zero-copy: an ImageBitmap of each atlas region is handed to the character's canvas.
      presenting = jobs.length;
      const sent = performance.now();
      jobs.forEach(function (j) {
        const ch = j.ch;
        createImageBitmap(glCanvas, j.x, j.y, j.w, j.h).then(function (bmp) {
          if (!ch.canvas.isConnected) { bmp.close(); return; }
          if (ch.canvas.width !== j.w || ch.canvas.height !== j.h) { ch.canvas.width = j.w; ch.canvas.height = j.h; }
          const ctx = ch.bmr || (ch.bmr = ch.canvas.getContext('bitmaprenderer'));
          if (ctx) { ctx.transferFromImageBitmap(bmp); shown(ch); } else bmp.close();
        }).catch(function () { bitmapsOK = false; }).then(function () {
          if (--presenting === 0) { if (!gl2) adapt(performance.now() - sent); schedule(); }
        });
      });
    } else {
      jobs.forEach(function (j) {
        const ch = j.ch;
        if (ch.bmr) { rebind(ch); return; }
        if (ch.canvas.width !== j.w || ch.canvas.height !== j.h) { ch.canvas.width = j.w; ch.canvas.height = j.h; }
        const ctx = ch.ctx || (ch.ctx = ch.canvas.getContext('2d'));
        ctx.clearRect(0, 0, j.w, j.h);
        ctx.drawImage(glCanvas, j.x, j.y, j.w, j.h, 0, 0, j.w, j.h);
        if (!ch.shown) verify(ch, ctx, j.w, j.h);
      });
      if (!gl2) adapt(performance.now() - t0);
      schedule();
    }
  }
  /* A canvas that already has a bitmaprenderer context cannot switch to 2D: swap in a fresh one. */
  function rebind(ch) {
    const c = ch.canvas.cloneNode(false);
    drop(ch); ch.canvas.replaceWith(c); delete c._cp3d;
    ch.canvas = c; ch.bmr = null; ch.ctx = null; c._cp3d = ch; ch.cssW = 0;
    chars.add(ch); if (io) io.observe(c); if (ro) ro.observe(c);
  }
  function schedule() { if (!raf && gl && !failed && !document.hidden) raf = requestAnimationFrame(draw); }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { last = 0; schedule(); } });
  reduce.addEventListener && reduce.addEventListener('change', function () { fpsCap = Math.min(fpsCap, maxFps()); schedule(); });

  const io = 'IntersectionObserver' in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { const ch = e.target._cp3d; if (ch) ch.visible = e.isIntersecting; });
    schedule();
  }, { rootMargin: '80px' }) : null;
  const ro = 'ResizeObserver' in window ? new ResizeObserver(function (entries) {
    entries.forEach(function (e) { const ch = e.target._cp3d; if (!ch) return; const b = e.contentBoxSize && e.contentBoxSize[0]; ch.cssW = b ? b.inlineSize : e.contentRect.width; ch.cssH = b ? b.blockSize : e.contentRect.height; });
    schedule();
  }) : null;
  if (!ro) window.addEventListener('resize', function () { chars.forEach(function (ch) { ch.cssW = 0; }); schedule(); }, { passive: true });

  function prep(spec) {
    if (spec.rgb) return spec;
    spec.rgb = hex(spec.color); spec.footRgb = hex(spec.foot || '#3b3f58'); spec.irisRgb = hex(spec.iris || '#4a2c1a');
    spec.accARgb = hex(spec.accA || '#ff7a59'); spec.accBRgb = hex(spec.accB || '#ffd43b');
    return spec;
  }

  window.CP3D = {
    /* Cheap capability check (no shader compile, never blocks). */
    supported: function () { return probe() && !failed; },
    /* Attach a character to a <canvas>. Returns a controller. */
    attach: function (canvas, spec, opts) {
      if (!probe() || failed) return null;
      opts = opts || {};
      const ch = { canvas: canvas, spec: prep(spec), motion: opts.motion || spec.motion || 'idle', prop: opts.prop !== undefined ? opts.prop : spec.prop, acc: opts.acc, orbs: opts.orbs || [], face: opts.face || {}, seed: opts.seed || Math.random() * 20, visible: !io, x: 0, propColors: opts.propColors, blank: 0 };
      canvas._cp3d = ch;
      chars.add(ch);
      if (io) io.observe(canvas);
      if (ro) ro.observe(canvas);
      if (!ready) startCompile();
      schedule();
      return ch;
    },
    detach: function (ch) { if (ch) drop(ch); },
    /* Pointer look: give client coordinates; characters near it look at it. */
    pointer: function (x, y) {
      chars.forEach(function (ch) {
        if (x === null) { ch.pointer = null; return; }
        if (!ch.visible) return;
        const r = ch.canvas.getBoundingClientRect();
        const nx = ((x - r.left) / r.width - 0.5) * 2, ny = -((y - r.top) / r.height - 0.5) * 2;
        if (Math.abs(nx) > 3 || Math.abs(ny) > 3) { ch.pointer = null; return; }
        const asp = r.width / r.height;
        const d = 3.6;
        ch.pointer = [nx * CAM.tan * asp * d, CAM.tgt[1] + ny * CAM.tan * d, CAM.pos[2] - d];
      });
    },
    kick: schedule,
    /* Render one pose at time t into a w×h image (used by scripts/bake_characters.cjs). */
    still: function (spec, opts, w, h, t) {
      if (!probe() || failed) return null;
      if (!ready) { startCompile(); if (prog && (!parallel || gl.getProgramParameter(prog, parallel.COMPLETION_STATUS_KHR))) { try { finishProgram(); } catch (e) { fail(e); return null; } } if (!ready) return null; }
      opts = opts || {};
      const ch = { spec: prep(spec), motion: opts.motion || 'idle', prop: opts.prop !== undefined ? opts.prop : spec.prop, acc: opts.acc, orbs: opts.orbs || [], face: opts.face || {}, seed: 0, x: 0, nextBlink: t + 60 };
      if (glCanvas.width < w || glCanvas.height < h) { glCanvas.width = Math.max(glCanvas.width, w); glCanvas.height = Math.max(glCanvas.height, h); }
      const H = glCanvas.height;
      gl.viewport(0, H - h, w, h); gl.enable(gl.SCISSOR_TEST); gl.scissor(0, H - h, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(loc.uRes, w, h); if (loc.uOff) gl.uniform2f(loc.uOff, 0, H - h);
      for (let i = 0; i < 4; i++) frameCharacter(ch, t);   // settles eye tracking
      gl.drawArrays(gl.TRIANGLES, 0, 6); gl.disable(gl.SCISSOR_TEST);
      const c = document.createElement('canvas'); c.width = w; c.height = h;
      c.getContext('2d').drawImage(glCanvas, 0, 0, w, h, 0, 0, w, h);
      return c;
    },
    stats: function () { return Object.assign({ ready: ready, failed: failed, characters: chars.size, bitmaps: bitmapsOK }, stats); },
    PROPS: Object.keys(PROPS), ACCS: Object.keys(ACCS), ORBS: Object.keys(ORBS), MOTIONS: Object.keys(MOTIONS)
  };
})();
