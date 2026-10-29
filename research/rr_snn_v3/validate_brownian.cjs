"use strict";
function validateRRBrownian(B) {
  const checks=[],raw={};
  const assert=(ok,name,detail)=>{checks.push({name,passed:Boolean(ok),detail});if(!ok)throw new Error(name);};
  const max=(a)=>Math.max(0,...a.map(Math.abs));
  // Independent quadrature uses only the standard Gaussian density.
  const normalGrid=[-8,-4,-2,-1,0,1,2,4,8];
  const normalErrors=normalGrid.map(z=>B.Phi(z)-B.integrate(
    t=>Math.exp(-t*t/2)/Math.sqrt(2*Math.PI),-12,z,1e-13));
  assert(max(normalErrors)<3e-12,"normal CDF vs independent density integral",max(normalErrors));
  assert(Math.abs(B.logPhi(-20)+203.9171553710973)<1e-12,
    "log-tail remains finite below ordinary CDF resolution",B.logPhi(-20));
  const massErrors=[];
  for(const x of [.001,.01,.1,1,4,10])for(const mu of [-4,-1,0,1,4])
    for(const t of [.01,.1,1,10]) {
      const p=B.probabilities(x,mu,1,t);
      massErrors.push(p.hit+p.survival-1);
      if(p.hit<0||p.hit>1||p.survival<0||p.survival>1)throw new Error("probability range");
    }
  assert(max(massErrors)<2e-12,"120 hit and survival mass cases",max(massErrors));
  const cases=[[.8,.1,.7,1],[1,0,1,1],[.4,-.3,.6,.8],[1.2,.8,.9,1.4]];
  const densities=[],gradients=[],semigroups=[],quantiles=[];
  for(const [x,mu,sigma,t] of cases) {
    const p=B.probabilities(x,mu,sigma,t),sd=sigma*Math.sqrt(t);
    const upper=Math.max(x+mu*t,0)+12*sd+x;
    const k=z=>Math.exp(B.logKilledDensity(z,x,mu,sigma,t));
    const integral=B.integrate(k,0,upper,2e-12);
    const fd=(B.probabilities(x,mu,sigma,t+1e-5).hit-
      B.probabilities(x,mu,sigma,t-1e-5).hit)/2e-5;
    densities.push({x,mu,sigma,t,massError:integral-p.survival,
      derivativeError:fd-Math.exp(B.logFirstPassage(x,mu,sigma,t))});
    const score=B.firstPassageScore(x,mu,sigma,t),v=[x,mu,sigma];
    const gs=["x","mu","sigma"].map((key,j)=>{
      const h=1e-5*Math.max(.1,Math.abs(v[j])),plus=v.slice(),minus=v.slice();
      plus[j]+=h;minus[j]-=h;
      const d=(B.logFirstPassage(...plus,t)-B.logFirstPassage(...minus,t))/(2*h);
      return {key,analytic:score[key],finiteDifference:d,error:d-score[key]};
    });
    gradients.push(...gs);
    const y=x+.35,half=t*.4;
    const composed=B.integrate(z=>z===0?0:
      Math.exp(B.logKilledDensity(z,x,mu,sigma,half)+
        B.logKilledDensity(y,z,mu,sigma,t-half)),0,upper,1e-12);
    const direct=Math.exp(B.logKilledDensity(y,x,mu,sigma,t));
    semigroups.push({x,mu,sigma,t,direct,composed,error:composed-direct});
    for(const fraction of [.01,.2,.5,.9]) {
      const u=p.hit*fraction;
      const at=B.firstPassageQuantile(u,x,mu,sigma,t);
      quantiles.push({kind:"hit",error:B.probabilities(x,mu,sigma,at).hit-u});
      const z=B.survivorQuantile(fraction,x,mu,sigma,t);
      quantiles.push({kind:"survivor",error:B.killedCdf(z,x,mu,sigma,t)/p.survival-fraction});
    }
  }
  const censoredGradients=[],endpointGradients=[];
  for(const [x,mu,sigma,t] of cases) {
    const v=[x,mu,sigma],S=B.survivalScore(x,mu,sigma,t),K=B.killedScore(x+.3,x,mu,sigma,t);
    for(let j=0;j<3;j++) {
      const key=["x","mu","sigma"][j],h=1e-5*Math.max(.1,Math.abs(v[j]));
      const hi=v.slice(),lo=v.slice();hi[j]+=h;lo[j]-=h;
      const fdS=(B.probabilities(...hi,t).logSurvival-B.probabilities(...lo,t).logSurvival)/(2*h);
      const fdK=(B.logKilledDensity(x+.3,...hi,t)-B.logKilledDensity(x+.3,...lo,t))/(2*h);
      censoredGradients.push({key,analytic:S[key],finiteDifference:fdS,error:fdS-S[key]});
      endpointGradients.push({key,analytic:K[key],finiteDifference:fdK,error:fdK-K[key]});
    }
  }
  assert(max(censoredGradients.map(x=>x.error))<3e-8,"12 censored survival score derivatives",
    max(censoredGradients.map(x=>x.error)));
  assert(max(endpointGradients.map(x=>x.error))<3e-8,"12 killed endpoint score derivatives",
    max(endpointGradients.map(x=>x.error)));
  raw.censoredGradients=censoredGradients;raw.endpointGradients=endpointGradients;
  raw.densities=densities;raw.gradients=gradients;raw.semigroups=semigroups;
  assert(max(densities.map(x=>x.massError))<2e-10,"killed density integrates to survival",
    max(densities.map(x=>x.massError)));
  assert(max(densities.map(x=>x.derivativeError))<2e-8,"CDF derivative equals first-passage density",
    max(densities.map(x=>x.derivativeError)));
  assert(max(gradients.map(x=>x.error))<3e-8,"12 first-passage score derivatives",
    max(gradients.map(x=>x.error)));
  assert(max(semigroups.map(x=>x.error))<2e-10,"killed Chapman-Kolmogorov composition",
    max(semigroups.map(x=>x.error)));
  assert(max(quantiles.map(x=>x.error))<2e-10,"32 inverse CDF residuals",
    max(quantiles.map(x=>x.error)));
  assert(B.firstPassageQuantile(.9,1,1,1,100)===null,
    "drift away from threshold retains non-hitting mass",{eventualHit:Math.exp(-2)});
  assert(B.probabilities(1,1,1,100).hit<Math.exp(-2)+1e-13,
    "finite-horizon hit does not exceed defective eventual probability",B.probabilities(1,1,1,100).hit);
  assert(JSON.stringify(B.probabilities(1,0,1,0))===
    JSON.stringify({hit:0,survival:1,logHit:-Infinity,logSurvival:0}),"zero-time distribution",null);
  // Fresh diagnostic seed; this is calibration, not architecture selection.
  let seed=2026102909;
  const uniform=()=>{seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;
    return ((seed>>>0)+.5)/4294967296;};
  const x=.8,mu=.1,sigma=.7,t=1,n=4096,upper=x+mu*t+12*sigma;
  const p=B.probabilities(x,mu,sigma,t);
  const k=z=>Math.exp(B.logKilledDensity(z,x,mu,sigma,t));
  const targetMean=B.integrate(z=>z*k(z),0,upper,2e-12)/p.survival;
  const targetSurvival=B.integrate(z=>z===0?0:k(z)*
    B.probabilities(z,-.6,.7,.75).survival,0,upper,2e-12)/p.survival;
  let sum=0,squares=0,secondHits=0;
  for(let i=0;i<n;i++) {
    const z=B.survivorQuantile(uniform(),x,mu,sigma,t);
    sum+=z;squares+=z*z;
    if(B.firstPassageQuantile(uniform(),z,-.6,.7,.75)!==null)secondHits++;
  }
  const mean=sum/n,se=Math.sqrt((squares/n-mean*mean)/n),survival=1-secondHits/n;
  raw.switchCalibration={seed:2026102909,n,condition:"survived first interval",
    targetMean,observedMean:mean,meanSE:se,targetSurvival,observedSurvival:survival,
    survivalSE:Math.sqrt(targetSurvival*(1-targetSurvival)/n)};
  assert(Math.abs(mean-targetMean)<5*se,"surviving endpoint conditional mean",raw.switchCalibration);
  assert(Math.abs(survival-targetSurvival)<5*raw.switchCalibration.survivalSE,
    "parameter switch after survival preserves killed-law conditioning",raw.switchCalibration);
  // Correct conditional law differs from drawing an unconditional Gaussian endpoint.
  const ordinaryMean=x+mu*t;
  assert(targetMean-ordinaryMean>.2,"survivors cannot be replaced by unconditional endpoints",
    {conditionalMean:targetMean,ordinaryMean});
  const fees=[0,.25,.5,.7,.8,1],thresholds=[.85,1,1.2,1.5,2];
  raw.thresholdFixture=fees.map(renewLoss=>{
    const choices=[{threshold:"immediate",value:.8},...thresholds.map(threshold=>({
      threshold,...B.thresholdValue({evidence:.8,drift:-.1,sigma:.3,deadline:1,threshold,renewLoss})}))];
    return {renewLoss,best:choices.reduce((a,b)=>b.value>a.value?b:a),choices};
  });
  assert(raw.thresholdFixture[0].best.threshold===2 &&
    raw.thresholdFixture[4].best.threshold==="immediate","renewal fee changes restricted optimal pulse timing",
    raw.thresholdFixture.map(x=>({fee:x.renewLoss,threshold:x.best.threshold,value:x.best.value})));
  assert(raw.thresholdFixture.every((x,i,a)=>i===0||x.best.value<=a[i-1].best.value+1e-10),
    "value nonincreasing under common renewal fee",null);
  const invalid=[
    ()=>B.probabilities(0,0,1,1),()=>B.probabilities(1,0,0,1),
    ()=>B.probabilities(1,NaN,1,1),()=>B.probabilities(1,0,1,-1),
    ()=>B.firstPassageQuantile(0,1,0,1,1),()=>B.firstPassageQuantile(1,1,0,1,1),
    ()=>B.survivorQuantile(.5,1,-20,1,1),()=>B.killedCdf(-1,1,0,1,1),
    ()=>B.firstPassageScore(1,0,1,0),()=>B.probabilities(1e-100,0,1,1),
    ()=>B.thresholdValue({evidence:1,drift:0,sigma:1,deadline:1,threshold:1,renewLoss:0})
  ];
  const rejected=invalid.map(fn=>{try{fn();return false;}catch{return true;}});
  assert(rejected.every(Boolean),"11 invalid or unresolved numerical cases reject",rejected);
  return {schema:"rr-snn-v3-brownian-validation-1",execution:"pure JavaScript V8",
    passed:checks.length,checks,raw,claims:{analyticIntervalFormulas:true,
      inverseCdfNumerical:true,continuationQuadratureNumerical:true,
      wholeNetworkTraining:false,globalMovingBoundaryOptimality:false}};
}
if(typeof module!=="undefined")module.exports=validateRRBrownian;
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(validateRRBrownian(require("./brownian_interval.cjs")),null,2));
