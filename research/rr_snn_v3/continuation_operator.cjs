"use strict";

/*
 * RR-SNN v3 research primitive: continuation-valued deadline control.
 * This finite-state/event-grid reference is not a trained SNN or a production
 * profile. It has no host, network, filesystem, or third-party dependencies.
 */
const RRContinuation = (() => {
  const requireThat = (ok, message) => { if (!ok) throw new Error(message); };
  const identity = n => Array.from({length:n}, (_,i) =>
    Array.from({length:n}, (_,j) => Number(i===j)));
  function multiply(A,B) {
    return A.map(row => B[0].map((_,j) =>
      row.reduce((sum,x,k)=>sum+x*B[k][j],0)));
  }
  function apply(P,v) {
    requireThat(P.length===v.length && v.every(Number.isFinite),"invalid value vector");
    return P.map(row=>row.reduce((sum,p,j)=>sum+p*v[j],0));
  }
  function validateGenerator(Q) {
    requireThat(Array.isArray(Q) && Q.length>0 && Q.length<=32,"generator dimension");
    const n=Q.length;
    for(let i=0;i<n;i++) {
      requireThat(Array.isArray(Q[i]) && Q[i].length===n,"generator shape");
      requireThat(Q[i].every(Number.isFinite),"nonfinite generator");
      requireThat(Q[i][i]<=0,"positive generator diagonal");
      requireThat(Q[i][i]!==0||Q[i].every(x=>x===0),"inconsistent zero exit rate");
      requireThat(Q[i].every((x,j)=>j===i || x>=0),"negative transition rate");
      const scale=Math.max(1,...Q[i].map(Math.abs));
      requireThat(Math.abs(Q[i].reduce((a,b)=>a+b,0))<=1e-12*scale,"generator row mass");
    }
  }
  function transition(Q,dt,tolerance=1e-13) {
    validateGenerator(Q);
    requireThat(Number.isFinite(dt)&&dt>=0,"invalid elapsed time");
    requireThat(Number.isFinite(tolerance)&&tolerance>=1e-15&&tolerance<=1e-6,"invalid tolerance");
    const n=Q.length, rate=Math.max(...Q.map((r,i)=>-r[i]));
    if(dt===0 || rate===0) return {matrix:identity(n),poissonTailBound:0,pieces:1};
    const pieces=Math.ceil(rate*dt/8);
    requireThat(pieces<=4096,"declared propagation work cap exceeded");
    const z=rate*dt/pieces, R=identity(n).map((r,i)=>r.map((x,j)=>x+Q[i][j]/rate));
    let power=identity(n),weight=Math.exp(-z),tail=Infinity;
    const one=power.map(r=>r.map(x=>x*weight));
    for(let k=1;k<=512;k++) {
      power=multiply(power,R);weight*=z/k;
      for(let i=0;i<n;i++) for(let j=0;j<n;j++) one[i][j]+=weight*power[i][j];
      const next=weight*z/(k+1);
      tail=k+2>z ? next/(1-z/(k+2)) : Infinity;
      if(tail<=tolerance/pieces) break;
      requireThat(k<512,"Poisson sum did not converge");
    }
    let matrix=identity(n);
    for(let k=0;k<pieces;k++) matrix=multiply(matrix,one);
    return {matrix,poissonTailBound:Math.min(1,pieces*tail),pieces};
  }
  function continueValue(Q,dt,postValue,rho=0) {
    requireThat(Number.isFinite(rho)&&rho>=0,"invalid discount rate");
    return apply(transition(Q,dt).matrix,postValue).map(x=>x*Math.exp(-rho*dt));
  }

  /*
   * Each action is atomically evaluated from one post-action state.
   * Utility loss and budget debit are separately specified units.
   * All emits use pre-action evidence; a joint burst resets evidence once.
   * Action availability does not inspect the hidden value oracle.
   */
  function deadlineChoices({budget,evidence,resetEvidence,legs,continuation}) {
    requireThat(Number.isSafeInteger(budget)&&budget>=0,"invalid budget");
    requireThat(Number.isFinite(evidence)&&Number.isFinite(resetEvidence),"invalid evidence");
    requireThat(Array.isArray(legs)&&legs.length>0&&legs.length<=8,"leg count cap");
    requireThat(typeof continuation==="function","missing continuation value");
    for(const leg of legs) {
      requireThat(leg && ["renewDebit","emitDebit"].every(k=>
        Number.isSafeInteger(leg[k])&&leg[k]>=0),"invalid debit");
      requireThat(["renewLoss","emitReward"].every(k=>Number.isFinite(leg[k])) &&
        leg.renewLoss>=0,"invalid utility amount");
    }
    const choices=[];
    const visit=(j,actions,charge,loss,emittedReward,renewedMask,emitCount)=>{
      if(charge>budget) return;
      if(j===legs.length) {
        const next=Object.freeze({budget:budget-charge,evidence:emitCount?resetEvidence:evidence,
          renewedMask,emitCount});
        const tail=continuation(next);
        requireThat(Number.isFinite(tail),"nonfinite continuation");
        choices.push({actions:actions.join(""),charge,loss,emittedReward,
          next,value:emittedReward-loss+tail});
        return;
      }
      const leg=legs[j];
      visit(j+1,[...actions,"D"],charge,loss,emittedReward,renewedMask,emitCount);
      visit(j+1,[...actions,"R"],charge+leg.renewDebit,loss+leg.renewLoss,
        emittedReward,renewedMask|(1<<j),emitCount);
      visit(j+1,[...actions,"E"],charge+leg.emitDebit,loss,emittedReward+leg.emitReward,
        renewedMask,emitCount+1);
    };
    visit(0,[],0,0,0,0,0);
    requireThat(choices.length>0,"no feasible action");
    const best=choices.reduce((a,b)=>b.value>a.value?b:a);
    return {best,choices};
  }
  function resourceShock(budget,amount) {
    requireThat(Number.isSafeInteger(budget)&&budget>=0 &&
      Number.isSafeInteger(amount)&&amount>=0,"invalid resource event");
    return Math.max(0,budget-amount);
  }
  function exerciseOrRenew({evidence,terminalReward,renewLoss,outputCost,
      budget,renewDebit=1,emitDebit=1}) {
    for(const x of [evidence,terminalReward,renewLoss,outputCost])
      requireThat(Number.isFinite(x),"nonfinite exercise input");
    requireThat(renewLoss>=0 && outputCost>=0,"negative loss or cost");
    requireThat([budget,renewDebit,emitDebit].every(x=>Number.isSafeInteger(x)&&x>=0),
      "invalid exercise budget");
    const options=[{action:"drop",value:0,renewals:0}];
    if(budget>=emitDebit) options.push({action:"emit",value:evidence-outputCost,renewals:0});
    // Renewal also requires an affordable terminal output in this one-cycle model.
    if(budget>=renewDebit+emitDebit) options.push({action:"renew",
      value:Math.max(0,terminalReward-outputCost)-renewLoss,renewals:1});
    return options.reduce((a,b)=>b.value>a.value?b:a);
  }
  function directionCase(loss,placement="continuation",budget=2) {
    requireThat(["continuation","output_cost"].includes(placement),"unknown placement");
    const fee=placement==="continuation"?loss:0;
    const cost=placement==="output_cost"?loss:0;
    const due=[0.6,1].map(evidence=>exerciseOrRenew({evidence,terminalReward:1.5,
      renewLoss:fee,outputCost:cost,budget}));
    const Q=[[0,0],[Math.log(2),-Math.log(2)]];
    const wait=continueValue(Q,1,due.map(x=>x.value))[1];
    const output=budget>=1 ? 1-cost : -Infinity;
    const value=Math.max(0,output,wait);
    return {loss,placement,budget,outputValue:Number.isFinite(output)?output:null,
      waitValue:wait,value,action:value===0?"drop":value===output?"emit":value===wait?"wait":"drop",
      expectedRenewals:value===wait?0.5*(due[0].renewals+due[1].renewals):0,
      dueActions:due.map(x=>x.action)};
  }

  function normalPdf(x) { return Math.exp(-0.5*x*x)/Math.sqrt(2*Math.PI); }
  function simpson(f,a,b,eps=1e-12,maxDepth=24) {
    requireThat(Number.isFinite(a)&&Number.isFinite(b)&&a<=b,"quadrature interval");
    const mid=(a+b)/2, fa=f(a),fm=f(mid),fb=f(b);
    const initial=(b-a)*(fa+4*fm+fb)/6;
    function recur(a,b,fa,fm,fb,whole,tol,depth) {
      const m=(a+b)/2,l=(a+m)/2,r=(m+b)/2,fl=f(l),fr=f(r);
      const left=(m-a)*(fa+4*fl+fm)/6,right=(b-m)*(fm+4*fr+fb)/6;
      const error=left+right-whole;
      if(Math.abs(error)<=15*tol) return left+right+error/15;
      requireThat(depth>0,"quadrature depth exhausted");
      return recur(a,m,fa,fl,fm,left,tol/2,depth-1)+
        recur(m,b,fm,fr,fb,right,tol/2,depth-1);
    }
    return recur(a,b,fa,fm,fb,initial,eps,maxDepth);
  }
  function normalCdf(x) {
    if(x<=-10) return 0;
    if(x>=10) return 1;
    return x<0?0.5-simpson(normalPdf,0,-x,1e-14):
      0.5+simpson(normalPdf,0,x,1e-14);
  }
  function positiveNormalMean(mean,sd) {
    requireThat(Number.isFinite(mean)&&Number.isFinite(sd)&&sd>=0,"invalid Gaussian");
    if(sd===0) return Math.max(0,mean);
    const d=mean/sd;
    return Math.max(0,sd*normalPdf(d)+mean*normalCdf(d));
  }
  function brownianDirection(loss,placement="continuation",budget=2) {
    requireThat(Number.isFinite(loss)&&loss>=0,"invalid loss");
    requireThat(["continuation","output_cost"].includes(placement),"unknown placement");
    requireThat(Number.isSafeInteger(budget)&&budget>=0,"invalid budget");
    const fee=placement==="continuation"?loss:0;
    const cost=placement==="output_cost"?loss:0;
    const output=budget>=1?1-cost:-Infinity;
    function due(y) {
      const emit=budget>=1?Math.max(0,y-cost):0;
      const renew=budget>=2?positiveNormalMean(y+0.7-cost,0.2)-fee:-Infinity;
      return Math.max(0,emit,renew);
    }
    // Explicit three-decision-time model: t=0, D=1, H=2.
    // Y_D ~ N(0.8,0.2^2); after renewal drift=+0.7, sigma=0.2.
    const integrand=z=>normalPdf(z)*due(0.8+0.2*z);
    const wait=simpson(integrand,-10,0,2e-12)+simpson(integrand,0,10,2e-12);
    const value=Math.max(0,output,wait);
    return {loss,placement,budget,outputValue:Number.isFinite(output)?output:null,waitValue:wait,
      action:value===0?"drop":value===output?"emit":"wait",value};
  }
  function twoDeadlineDecision(futureFees) {
    requireThat(Array.isArray(futureFees)&&futureFees.length>0&&futureFees.length<=64,
      "invalid future fee distribution");
    requireThat(futureFees.every(x=>x&&Number.isFinite(x.fee)&&x.fee>=0&&
      Number.isFinite(x.probability)&&x.probability>=0)&&
      Math.abs(futureFees.reduce((a,x)=>a+x.probability,0)-1)<1e-12,
      "future fee probabilities");
    // Current action sees this public distribution, never a realized future fee.
    // At t2 the fee is observed, so its action is selected inside the expectation.
    return deadlineChoices({budget:2,evidence:1,resetEvidence:0,
      legs:[{renewDebit:1,emitDebit:1,renewLoss:.25,emitReward:2.5}],
      continuation:first=>futureFees.reduce((expected,scenario)=>{
        const second=deadlineChoices({budget:first.budget,evidence:first.evidence,
          resetEvidence:0,legs:[{renewDebit:1,emitDebit:1,renewLoss:scenario.fee,
            emitReward:first.evidence}],
          continuation:last=>last.evidence*
            ((first.renewedMask&1?1:0)+(last.renewedMask&1?3:0))});
        return expected+scenario.probability*second.best.value;
      },0)});
  }
  return {identity,multiply,apply,transition,continueValue,deadlineChoices,twoDeadlineDecision,
    resourceShock,exerciseOrRenew,directionCase,brownianDirection,positiveNormalMean};
})();
if(typeof module!=="undefined") module.exports=RRContinuation;
