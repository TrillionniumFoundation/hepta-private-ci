"use strict";

/*
 * Brownian interval primitives for a distance X=x+mu*t+sigma*W, killed at zero.
 * The first-passage and killed-transition formulas are analytic. Their inverse
 * CDFs and continuation integrals below are numerical evaluations, not a claim
 * of a closed-form moving boundary or a continuously optimal policy.
 */
const RRBrownian = (() => {
  const check=(ok,msg)=>{if(!ok)throw new Error(msg);};
  const LOG2=Math.log(2), LOG2PI=Math.log(2*Math.PI), LOGPI=Math.log(Math.PI);
  function log1mexp(a) {
    check(a<=0,"log difference order");
    return a < -LOG2 ? Math.log1p(-Math.exp(a)) : Math.log(-Math.expm1(a));
  }
  function logadd(a,b) {
    if(a===-Infinity)return b;
    if(b===-Infinity)return a;
    const m=Math.max(a,b);return m+Math.log1p(Math.exp(Math.min(a,b)-m));
  }
  function logdiff(a,b) {
    if(b===-Infinity)return a;
    if(a===b)return -Infinity;
    check(a>b,"negative probability from cancellation");
    return a+log1mexp(b-a);
  }
  function logPhi(z) {
    check(Number.isFinite(z),"nonfinite normal argument");
    if(z===0)return -LOG2;
    const u=Math.abs(z), x=.5*u*u;
    check(Number.isFinite(x),"normal argument overflow");
    let logTail;
    if(x<1.5) {
      let term=2,sum=term;
      for(let n=1;n<256;n++) {
        term*=x/(.5+n);sum+=term;
        if(term<=sum*2e-16)break;
        check(n<255,"normal series work cap");
      }
      const erf=x===0?0:sum*Math.exp(-x+.5*Math.log(x)-.5*LOGPI);
      logTail=-LOG2+Math.log1p(-erf);
    } else {
      let b=x+.5,c=1e300,d=1/b,h=d,done=false;
      for(let n=1;n<=512;n++) {
        const a=-n*(n-.5);b+=2;
        d=a*d+b;if(Math.abs(d)<1e-300)d=1e-300;
        c=b+a/c;if(Math.abs(c)<1e-300)c=1e-300;
        d=1/d;const delta=d*c;h*=delta;
        if(Math.abs(delta-1)<3e-15){done=true;break;}
      }
      check(done&&h>0,"normal continued fraction work cap");
      logTail=-LOG2-x+.5*Math.log(x)-.5*LOGPI+Math.log(h);
    }
    return z<0?logTail:log1mexp(logTail);
  }
  const Phi=z=>Math.exp(logPhi(z));
  function normalInterval(lo,hi) {
    check(lo<=hi,"normal interval order");
    if(lo===hi)return -Infinity;
    if(hi<=0)return logdiff(logPhi(hi),logPhi(lo));
    if(lo>=0)return logdiff(logPhi(-lo),logPhi(-hi));
    return Math.log1p(-Math.exp(logPhi(lo))-Math.exp(logPhi(-hi)));
  }
  function args(x,mu,sigma,t) {
    check([x,mu,sigma,t].every(Number.isFinite)&&x>0&&sigma>0&&t>=0,
      "invalid Brownian parameters");
    check(x<=1e100&&Math.abs(mu)<=1e100&&sigma<=1e100&&t<=1e100,
      "Brownian parameter magnitude cap");
    const sd=sigma*Math.sqrt(t);
    check(t===0||(sd>0&&Number.isFinite(sd)),"Brownian scale underflow or overflow");
    return sd;
  }
  function probabilities(x,mu,sigma,t) {
    const sd=args(x,mu,sigma,t);
    if(t===0)return {hit:0,survival:1,logHit:-Infinity,logSurvival:0};
    const a=x/sd,b=mu*Math.sqrt(t)/sigma;
    check(Number.isFinite(a)&&Number.isFinite(b),"Brownian standardized overflow");
    const logA=logPhi(-a-b),logB=-2*a*b+logPhi(-a+b);
    const logHit=Math.min(0,logadd(logA,logB));
    // Direct difference avoids subtracting a rounded-to-one hit probability.
    const s1=logPhi(a+b),s2=logB;
    check(s1>s2,"survival cancellation exceeds floating-point resolution");
    const logSurvival=logdiff(s1,s2);
    return {hit:Math.exp(logHit),survival:Math.exp(logSurvival),logHit,logSurvival};
  }
  function logFirstPassage(x,mu,sigma,t) {
    args(x,mu,sigma,t);
    if(t===0)return -Infinity;
    const z=(x+mu*t)/(sigma*Math.sqrt(t));
    return Math.log(x)-Math.log(sigma)-.5*LOG2PI-1.5*Math.log(t)-.5*z*z;
  }
  function firstPassageScore(x,mu,sigma,t) {
    args(x,mu,sigma,t);check(t>0,"score requires positive passage time");
    const d=x+mu*t;
    const score={x:1/x-d/(sigma*sigma*t),mu:-d/(sigma*sigma),
      sigma:-1/sigma+d*d/(sigma*sigma*sigma*t)};
    check(Object.values(score).every(Number.isFinite),"first passage score overflow");
    return score;
  }
  function survivalScore(x,mu,sigma,t) {
    const sd=args(x,mu,sigma,t);
    if(t===0)return {x:0,mu:0,sigma:0};
    const p=probabilities(x,mu,sigma,t),a=x/sd,b=mu*Math.sqrt(t)/sigma;
    const phiRatio=Math.exp(-.5*(a+b)*(a+b)-.5*LOG2PI-p.logSurvival);
    const imageRatio=Math.exp(-2*a*b+logPhi(-a+b)-p.logSurvival);
    const score={x:2*phiRatio/sd+2*mu*imageRatio/(sigma*sigma),
      mu:2*x*imageRatio/(sigma*sigma),
      sigma:-2*x*phiRatio/(sigma*sd)-4*mu*x*imageRatio/(sigma*sigma*sigma)};
    check(Object.values(score).every(Number.isFinite),"survival score overflow");
    return score;
  }
  function killedScore(z,x,mu,sigma,t) {
    const sd=args(x,mu,sigma,t);
    check(Number.isFinite(z)&&z>0&&t>0,"killed score requires positive endpoint and time");
    const v=z-x-mu*t,q=2*x*z/(sd*sd),r=q>700?0:1/Math.expm1(q);
    const score={x:v/(sd*sd)+2*z*r/(sd*sd),mu:v/(sigma*sigma),
      sigma:-1/sigma+v*v/(sigma*sd*sd)-4*x*z*r/(sigma*sd*sd)};
    check(Object.values(score).every(Number.isFinite),"killed score overflow");
    return score;
  }
  function logKilledDensity(z,x,mu,sigma,t) {
    const sd=args(x,mu,sigma,t);
    check(Number.isFinite(z)&&z>=0&&t>0,"invalid killed endpoint");
    if(z===0)return -Infinity;
    const v=(z-x-mu*t)/sd;
    return -.5*LOG2PI-Math.log(sd)-.5*v*v+log1mexp(-2*x*z/(sd*sd));
  }
  function killedCdf(z,x,mu,sigma,t) {
    const sd=args(x,mu,sigma,t);
    check(Number.isFinite(z)&&z>=0&&t>0,"invalid killed CDF endpoint");
    if(z===0)return 0;
    const a=x/sd,b=mu*Math.sqrt(t)/sigma,c=z/sd;
    const logA=normalInterval(-a-b,c-a-b);
    const logB=-2*a*b+normalInterval(a-b,c+a-b);
    check(logA>logB,"endpoint CDF cancellation exceeds floating-point resolution");
    return Math.exp(logdiff(logA,logB));
  }
  function firstPassageQuantile(u,x,mu,sigma,horizon) {
    check(Number.isFinite(u)&&u>0&&u<1,"quantile must be strictly between zero and one");
    args(x,mu,sigma,horizon);check(horizon>0,"positive quantile horizon required");
    if(Math.log(u)>=probabilities(x,mu,sigma,horizon).logHit)return null;
    let lo=0,hi=horizon;
    for(let n=0;n<96;n++) {
      const mid=(lo+hi)/2;
      if(mid===lo||mid===hi)break;
      if(probabilities(x,mu,sigma,mid).logHit<Math.log(u))lo=mid;else hi=mid;
    }
    return (lo+hi)/2;
  }
  function survivorQuantile(u,x,mu,sigma,t) {
    check(Number.isFinite(u)&&u>0&&u<1,"survivor quantile must be strictly between zero and one");
    const sd=args(x,mu,sigma,t);check(t>0,"positive survivor time required");
    const p=probabilities(x,mu,sigma,t);
    check(p.survival>=1e-12,"survivor inverse outside declared probability domain");
    const target=u*p.survival;
    let lo=0,hi=Math.max(x+mu*t,0)+8*sd+x;
    for(let n=0;killedCdf(hi,x,mu,sigma,t)<target;n++) {
      check(n<32,"survivor bracket work cap");hi*=2;
    }
    for(let n=0;n<80;n++) {
      const mid=(lo+hi)/2;
      if(mid===lo||mid===hi)break;
      if(killedCdf(mid,x,mu,sigma,t)<target)lo=mid;else hi=mid;
    }
    return (lo+hi)/2;
  }
  function interval(uHit,uEnd,x,mu,sigma,t) {
    const at=firstPassageQuantile(uHit,x,mu,sigma,t);
    return at===null?{kind:"survivor",time:t,x:survivorQuantile(uEnd,x,mu,sigma,t)}:
      {kind:"hit",time:at,x:0};
  }
  function integrate(f,a,b,tolerance=1e-10) {
    check([a,b,tolerance].every(Number.isFinite)&&a<=b&&tolerance>0,"quadrature input");
    function step(a,b,fa,fm,fb,value,tol,depth) {
      const m=(a+b)/2,l=(a+m)/2,r=(m+b)/2,fl=f(l),fr=f(r);
      check([fl,fr].every(Number.isFinite),"nonfinite quadrature integrand");
      const left=(m-a)*(fa+4*fl+fm)/6,right=(b-m)*(fm+4*fr+fb)/6;
      const e=left+right-value;
      if(Math.abs(e)<=15*tol)return left+right+e/15;
      check(depth>0,"quadrature work cap");
      return step(a,m,fa,fl,fm,left,tol/2,depth-1)+step(m,b,fm,fr,fb,right,tol/2,depth-1);
    }
    if(a===b)return 0;
    const m=(a+b)/2,fa=f(a),fm=f(m),fb=f(b);
    check([fa,fm,fb].every(Number.isFinite),"nonfinite quadrature integrand");
    return step(a,b,fa,fm,fb,(b-a)*(fa+4*fm+fb)/6,tolerance,24);
  }
  function positiveNormal(mean,sd) {
    check(Number.isFinite(mean)&&Number.isFinite(sd)&&sd>0,"positive normal parameters");
    const z=mean/sd;return Math.max(0,mean*Phi(z)+sd*Math.exp(-.5*z*z-.5*LOG2PI));
  }
  function thresholdValue({evidence,drift,sigma,deadline,threshold,renewLoss}) {
    check([evidence,drift,sigma,deadline,threshold,renewLoss].every(Number.isFinite)&&
      sigma>0&&deadline>0&&threshold>evidence&&renewLoss>=0,"threshold fixture parameters");
    const x=threshold-evidence,mu=-drift,sd=sigma*Math.sqrt(deadline);
    const p=probabilities(x,mu,sigma,deadline);
    // One current cohort, budget 2, pulse/renewal each debit 1; pulse ends cohort.
    // At D choose output, drop, or renewal to D+1 with drift +.7, then terminal output.
    const due=y=>Math.max(0,y,positiveNormal(y+.7,sigma)-renewLoss);
    const upper=Math.max(x+mu*deadline,0)+12*sd+x;
    const f=z=>Math.exp(logKilledDensity(z,x,mu,sigma,deadline))*due(threshold-z);
    // Subdivide around density peak so adaptive integration cannot miss a narrow mode.
    const cuts=[0,upper,...[x+mu*deadline-4*sd,x+mu*deadline,x+mu*deadline+4*sd]
      .filter(z=>z>0&&z<upper)].sort((a,b)=>a-b);
    let terminal=0;for(let i=1;i<cuts.length;i++)terminal+=integrate(f,cuts[i-1],cuts[i],2e-11);
    return {value:threshold*p.hit+terminal,hitProbability:p.hit,survivorContinuation:terminal,
      integrationUpper:upper,scope:"fixed threshold until first external deadline; cohort ends on output"};
  }
  return {logPhi,Phi,normalInterval,probabilities,logFirstPassage,firstPassageScore,
    logKilledDensity,killedCdf,survivalScore,killedScore,firstPassageQuantile,survivorQuantile,interval,integrate,
    positiveNormal,thresholdValue};
})();
if(typeof module!=="undefined")module.exports=RRBrownian;
