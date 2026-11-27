"use strict";
function validateCtmcGradients(G,C,protocol,includeHoldout=true){
 const checks=[],assert=(ok,name)=>{if(!ok)throw new Error(name);checks.push(name);};
 const maxerr=(A,B)=>Math.max(...A.flat().map((x,i)=>Math.abs(x-B.flat()[i])));
 const mul=(A,B)=>A.map(r=>B[0].map((_,j)=>r.reduce((s,x,k)=>s+x*B[k][j],0)));
 const add=(A,B)=>A.map((r,i)=>r.map((x,j)=>x+B[i][j]));
 const perturb=(A,E,h)=>A.map((r,i)=>r.map((x,j)=>x+h*E[i][j]));
 function exact(a,b,t,da,db){
  const s=a+b,e=Math.exp(-s*t),u=a/s,v=b/s,ds=da+db;
  const p01=u*(1-e),p10=v*(1-e);
  const d01=(da-u*ds)/s*(1-e)+u*t*e*ds;
  const d10=(db-v*ds)/s*(1-e)+v*t*e*ds;
  return {P:[[1-p01,p01],[p10,1-p10]],D:[[-d01,d01],[d10,-d10]]};
 }
 let goldError=0,fdError=0,cases=0;
 for(const a of [.03,.7,4])for(const b of [.08,1.3])for(const t of [0,.2,1.7,12])for(let j=0;j<2;j++){
  const Q=[[-a,a],[b,-b]],E=j===0?[[-a,a],[0,0]]:[[0,0],[b,-b]];
  const got=G.transitionTangent(Q,E,t),want=exact(a,b,t,j===0?a:0,j===1?b:0);
  goldError=Math.max(goldError,maxerr(got.matrix,want.P),maxerr(got.derivative,want.D));cases++;
 }
 assert(goldError<2e-11,"48 two-state transitions and log-rate derivatives");
 const Q=[[-1.2,.7,.5],[.3,-1.1,.8],[.4,.2,-.6]],E=[[-.7,.7,0],[0,-.8,.8],[0,0,0]],dt=1.7,h=1e-5;
 const got=G.transitionTangent(Q,E,dt),plus=C.transition(perturb(Q,E,h),dt).matrix,minus=C.transition(perturb(Q,E,-h),dt).matrix;
 const fd=plus.map((r,i)=>r.map((x,j)=>(x-minus[i][j])/(2*h)));fdError=maxerr(got.derivative,fd);
 assert(fdError<2e-8,"noncommuting three-state Frechet finite difference");
 const p=G.transitionTangent(Q,E,.6),q=G.transitionTangent(Q,E,1.1);
 assert(maxerr(got.derivative,add(mul(p.derivative,q.matrix),mul(p.matrix,q.derivative)))<2e-11,"derivative semigroup product rule");
 const z=G.transitionTangent([[0,0],[0,0]],[[-1,1],[0,0]],2);
 assert(maxerr(z.derivative,[[-2,2],[0,0]])===0,"zero-generator directional derivative");
 let scaleError=0;
 for(const scale of [1e-100,1e-10,1,1e10,1e100]){
  const v=G.transitionTangent([[-.7*scale,.7*scale],[.3*scale,-.3*scale]],[[-.7*scale,.7*scale],[0,0]],1.2/scale);
  scaleError=Math.max(scaleError,maxerr(v.derivative,exact(.7,.3,1.2,.7,0).D));
 }
 assert(scaleError<2e-11,"five reciprocal rate/time scales");
 const g=[1,2,4],dg=[.2,-.3,.4],rho=.2,drho=.1;
 const cv=G.continuationTangent({Q,dQ:E,dt,postValue:g,dPostValue:dg,rho,dRho:drho});
 const cvp=C.continueValue(perturb(Q,E,h),dt,g.map((x,i)=>x+h*dg[i]),rho+h*drho);
 const cvm=C.continueValue(perturb(Q,E,-h),dt,g.map((x,i)=>x-h*dg[i]),rho-h*drho);
 const cve=Math.max(...cv.derivative.map((x,i)=>Math.abs(x-(cvp[i]-cvm[i])/(2*h))));
 assert(cve<2e-8,"continuation value, terminal direction and discount direction");
 const path=[{dt:.2,rates:[2],dRates:[2],mark:0},{dt:.4,rates:[3],dRates:[0],mark:0},{dt:.25,rates:[2],dRates:[2],mark:null}];
 const ps=G.markedPathScore({segments:path});
 assert(Math.abs(ps.logLikelihood-(Math.log(6)-2.1))<1e-14&&Math.abs(ps.score-.1)<1e-14,"multijump path includes final censored exposure");
 const self=G.markedPathScore({segments:[{dt:.1,rates:[2,5],dRates:[0,5],mark:1},{dt:.2,rates:[2,5],dRates:[0,5],mark:0},{dt:.3,rates:[2,5],dRates:[0,5],mark:null}]});
 assert(Math.abs(self.score+2)<1e-14&&self.eventCount===2,"marked self-event competes with every eligible channel");
 const ll=v=>G.markedPathScore({segments:path.map(s=>({...s,rates:s.rates.map((r,i)=>r*Math.exp(v*(s.dRates[i]?1:0))),dRates:[0]}))}).logLikelihood;
 assert(Math.abs((ll(h)-ll(-h))/(2*h)-ps.score)<2e-8,"full path score finite difference");
 const no=G.markedPathScore({segments:[{dt:.8,rates:[2],dRates:[2],mark:null},{dt:.4,rates:[],dRates:[],mark:null}]});
 assert(no.score===-1.6&&no.logLikelihood===-1.6,"no-event censor and zero-hazard refractory exposure");
 const bad=[()=>G.transitionTangent([[-1,2],[0,0]],[[-1,1],[0,0]],1),
  ()=>G.transitionTangent([[-1e-100,2e-100],[0,0]],[[-1,1],[0,0]],1e100),
  ()=>G.transitionTangent([[-1,1],[0,0]],[[1,1],[0,0]],1),
  ()=>G.transitionTangent(Q,E,-1),()=>G.transitionTangent(Q,E,1e8),
  ()=>G.markedPathScore({segments:[{dt:1,rates:[0],dRates:[1],mark:0}]}),
  ()=>G.markedPathScore({segments:[{dt:1,rates:[1],dRates:[0]}]}),
  ()=>G.markedPathScore({segments:[{dt:1e308,rates:[],dRates:[],mark:null},{dt:1e308,rates:[],dRates:[],mark:null}]}),
  ()=>G.continuationTangent({Q:[[0]],dQ:[[0]],dt:1e308,postValue:[1],rho:1e308,dRho:1e308})];
 let rejected=0;for(const fn of bad){try{fn();}catch(_){rejected++;}}
 assert(rejected===bad.length,"nine invalid/domain/work-cap cases rejected");
 function rng(seed){let a=seed>>>0;return ()=>{a=(a+0x6D2B79F5)>>>0;let t=a;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return (((t^(t>>>14))>>>0)+.5)/4294967296;};}
 function sample(seed,count){
  const random=rng(seed),out=[];
  for(let i=0;i<count;i++){
   const horizon=protocol.model.horizons[i%4],initial=Math.floor(i/4)%2;
   let state=initial,time=0;const segments=[];
   while(time<horizon){
    if(segments.length>=protocol.checks.max_jumps_per_path)throw new Error("sample path cap");
    const wait=-Math.log(random())/protocol.model.true_rates[state],remaining=horizon-time,dt=Math.min(wait,remaining),jump=wait<remaining;
    segments.push({state,dt,jump});time+=dt;if(jump)state=1-state;
   }
   out.push({initial,horizon,segments});
  }
  return out;
 }
 function stats(paths,omitFinal=false){
  const counts=[0,0],exposure=[0,0];
  for(const p of paths)for(const s of p.segments){if(!omitFinal||s.jump)exposure[s.state]+=s.dt;if(s.jump)counts[s.state]++;}
  return {counts,exposure};
 }
 function nll(S,rates,n){return rates.reduce((s,r,j)=>s+r*S.exposure[j]-S.counts[j]*Math.log(r),0)/n;}
 const train=sample(protocol.train.seed,protocol.train.paths),S=stats(train),mle=S.counts.map((n,j)=>n/S.exposure[j]);
 let theta=protocol.optimizer.initial_rates.map(Math.log);
 const initialNLL=nll(S,theta.map(Math.exp),train.length);
 for(let k=0;k<protocol.optimizer.steps;k++)theta=theta.map((x,j)=>x-protocol.optimizer.learning_rate*(Math.exp(x)*S.exposure[j]-S.counts[j])/train.length);
 const fitted=theta.map(Math.exp),relativeError=Math.max(...fitted.map((x,j)=>Math.abs(x-mle[j])/mle[j]));
 assert(relativeError<protocol.checks.optimizer_relative_error_to_MLE,"400-step log-rate gradient fit agrees with analytic censored MLE");
 let likelihoodError=0;
 for(const p of train.slice(0,8))for(let direction=0;direction<2;direction++){
  const actual=G.markedPathScore({segments:p.segments.map(s=>({dt:s.dt,rates:[fitted[s.state]],dRates:[s.state===direction?fitted[s.state]:0],mark:s.jump?0:null}))});
  const st=stats([p]),want=st.counts[direction]-fitted[direction]*st.exposure[direction];
  likelihoodError=Math.max(likelihoodError,Math.abs(actual.score-want));
 }
 assert(likelihoodError<1e-12,"trained-rate path scores match independent sufficient statistics");
 const report={checks_passed:checks.length,checks,cases,goldError,fdError,scaleError,continuationGradientError:cve,rejected,
  training:{paths:train.length,counts:S.counts,exposure:S.exposure,trueRates:protocol.model.true_rates,initialNLL,fitted,mle,relativeError,finalNLL:nll(S,fitted,train.length)}};
 if(includeHoldout){
  const hold=sample(protocol.holdout.seed,protocol.holdout.paths),HS=stats(hold),omitted=stats(train,true),biased=omitted.counts.map((n,j)=>n/omitted.exposure[j]);
  const brier=rates=>hold.reduce((sum,p)=>{const prediction=1-Math.exp(-rates[p.initial]*p.horizon),observed=Number(p.segments.some(s=>s.jump));return sum+(prediction-observed)**2;},0)/hold.length;
  report.holdout={paths:hold.length,counts:HS.counts,exposure:HS.exposure,countExposureRates:HS.counts.map((n,j)=>n/HS.exposure[j]),
   nllFitted:nll(HS,fitted,hold.length),nllTrue:nll(HS,protocol.model.true_rates,hold.length),nllOmitCensor:nll(HS,biased,hold.length),
   brierFitted:brier(fitted),brierTrue:brier(protocol.model.true_rates),brierOmitCensor:brier(biased),censorOmittingRates:biased};
 }
 return report;
}
if(typeof module!=="undefined")module.exports=validateCtmcGradients;
if(typeof require!=="undefined"&&require.main===module)console.log(JSON.stringify(validateCtmcGradients(
 require("./ctmc_gradients.cjs"),require("./continuation_operator.cjs"),require("./gradient_protocol.json")),null,2));
