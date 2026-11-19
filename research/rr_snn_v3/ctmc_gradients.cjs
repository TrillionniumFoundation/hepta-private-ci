"use strict";
// Research-only directional Frechet derivative and complete marked-path score.
// Row generators; fixed elapsed time; no differentiation of hard policy choices.
const RRCtmcGradients=(()=>{
 const check=(x,m)=>{if(!x)throw new Error(m);};
 const zero=n=>Array.from({length:n},()=>Array(n).fill(0));
 const eye=n=>zero(n).map((r,i)=>r.map((_,j)=>Number(i===j)));
 const mul=(A,B)=>A.map(r=>B[0].map((_,j)=>r.reduce((s,x,k)=>s+x*B[k][j],0)));
 const add=(A,B)=>A.map((r,i)=>r.map((x,j)=>x+B[i][j]));
 const mv=(A,v)=>A.map(r=>r.reduce((s,x,j)=>s+x*v[j],0));
 const norm=A=>Math.max(...A.map(r=>r.reduce((s,x)=>s+Math.abs(x),0)));
 function validate(Q,E){
  const n=Q.length;check(Array.isArray(Q)&&n>0&&n<=32,"generator dimension");
  check(Array.isArray(E)&&E.length===n,"direction shape");
  for(let i=0;i<n;i++){
   check(Array.isArray(Q[i])&&Q[i].length===n&&Q[i].every(Number.isFinite),"generator shape/value");
   check(Array.isArray(E[i])&&E[i].length===n&&E[i].every(Number.isFinite),"direction shape/value");
   check(Q[i][i]<=0&&Q[i].every((x,j)=>i===j||x>=0),"generator signs");
   const off=Q[i].reduce((s,x,j)=>s+(i===j?0:x),0),scale=Math.max(off,-Q[i][i]);
   check(Number.isFinite(off)&&((scale===0&&Q[i].every(x=>x===0))||
    (scale>0&&Math.abs(off+Q[i][i])<=1e-12*scale)),"generator row mass");
   const es=E[i].reduce((s,x)=>s+Math.abs(x),0);
   check(Number.isFinite(es)&&(es===0||Math.abs(E[i].reduce((s,x)=>s+x,0))<=1e-12*es),"direction row mass");
  }
 }
 function transitionTangent(Q,E,dt,tolerance=1e-13){
  validate(Q,E);check(Number.isFinite(dt)&&dt>=0,"elapsed time");
  check(Number.isFinite(tolerance)&&tolerance>=1e-15&&tolerance<=1e-6,"tolerance");
  const n=Q.length,nu=Math.max(...Q.map((r,i)=>-r[i])),en=norm(E);
  check(Number.isFinite(dt*en),"derivative scale overflow");
  if(dt===0||nu===0)return {matrix:eye(n),derivative:E.map(r=>r.map(x=>dt*x)),
   poissonTailBound:0,derivativeTailBound:0,pieces:1};
  const pieces=Math.max(1,Math.ceil(nu*dt/8));
  check(Number.isFinite(pieces)&&pieces<=4096,"propagation work cap");
  const h=dt/pieces,z=nu*h,R=eye(n).map((r,i)=>r.map((x,j)=>x+Q[i][j]/nu));
  const dR=E.map(r=>r.map(x=>x/nu));check(dR.flat().every(Number.isFinite),"direction scaling");
  let power=eye(n),dpower=zero(n),weight=Math.exp(-z);
  let P=power.map(r=>r.map(x=>x*weight)),D=zero(n),tail=Infinity,dTail=Infinity;
  for(let k=1;k<=512;k++){
   dpower=add(mul(dpower,R),mul(power,dR));power=mul(power,R);weight*=z/k;
   for(let i=0;i<n;i++)for(let j=0;j<n;j++){P[i][j]+=weight*power[i][j];D[i][j]+=weight*dpower[i][j];}
   const next=weight*z/(k+1);tail=k+2>z?next/(1-z/(k+2)):Infinity;
   dTail=pieces*h*en*(weight+tail)+(pieces-1)*dt*en*tail;
   if(pieces*tail<=tolerance&&dTail<=tolerance*Math.max(1,dt*en))break;
   check(k<512,"Poisson series cap");
  }
  let full=eye(n),dfull=zero(n);
  for(let k=0;k<pieces;k++){dfull=add(mul(dfull,P),mul(full,D));full=mul(full,P);}
  check(full.flat().every(Number.isFinite)&&dfull.flat().every(Number.isFinite),"nonfinite propagation");
  return {matrix:full,derivative:dfull,poissonTailBound:pieces*tail,derivativeTailBound:dTail,pieces};
 }
 function continuationTangent({Q,dQ,dt,postValue,dPostValue,rho=0,dRho=0}){
  const n=Q.length,dv=dPostValue||Array(n).fill(0);
  check(Array.isArray(postValue)&&postValue.length===n&&postValue.every(Number.isFinite),"post value");
  check(Array.isArray(dv)&&dv.length===n&&dv.every(Number.isFinite),"post value direction");
  check(Number.isFinite(rho)&&rho>=0&&Number.isFinite(dRho),"discount");
  const p=transitionTangent(Q,dQ,dt),base=mv(p.matrix,postValue),part=mv(p.derivative,postValue),vg=mv(p.matrix,dv),discount=Math.exp(-rho*dt);
  const value=base.map(x=>discount*x),derivative=part.map((x,i)=>discount*(x+vg[i]-dt*dRho*base[i]));
  check(value.every(Number.isFinite)&&derivative.every(Number.isFinite),"nonfinite continuation result");
  return {value,derivative,poissonTailBound:p.poissonTailBound,derivativeTailBound:p.derivativeTailBound};
 }
 function markedPathScore({segments,initialLogProbability=0,initialScore=0}){
  check(Array.isArray(segments)&&segments.length<=100000,"path segment cap");
  check(Number.isFinite(initialLogProbability)&&Number.isFinite(initialScore),"initial probability/score");
  let logLikelihood=initialLogProbability,score=initialScore,eventCount=0,exposureTime=0,integratedHazard=0;
  for(const s of segments){
   check(s&&Number.isFinite(s.dt)&&s.dt>=0,"path duration");
   check(Array.isArray(s.rates)&&Array.isArray(s.dRates)&&s.rates.length===s.dRates.length,"marked rates shape");
   check(s.rates.every(x=>Number.isFinite(x)&&x>=0)&&s.dRates.every(Number.isFinite),"marked rates");
   const total=s.rates.reduce((a,x)=>a+x,0),dtotal=s.dRates.reduce((a,x)=>a+x,0);
   check(Number.isFinite(total)&&Number.isFinite(dtotal)&&Number.isFinite(total*s.dt)&&Number.isFinite(dtotal*s.dt),"hazard overflow");
   logLikelihood-=s.dt*total;score-=s.dt*dtotal;exposureTime+=s.dt;integratedHazard+=s.dt*total;
   if(s.mark!==null){
    check(Number.isSafeInteger(s.mark)&&s.mark>=0&&s.mark<s.rates.length&&s.rates[s.mark]>0,"impossible observed mark");
    logLikelihood+=Math.log(s.rates[s.mark]);score+=s.dRates[s.mark]/s.rates[s.mark];eventCount++;
   }
  }
  check([logLikelihood,score,exposureTime,integratedHazard].every(Number.isFinite),"nonfinite path score");
  return {logLikelihood,score,eventCount,exposureTime,integratedHazard};
 }
 return {transitionTangent,continuationTangent,markedPathScore};
})();
if(typeof module!=="undefined")module.exports=RRCtmcGradients;
