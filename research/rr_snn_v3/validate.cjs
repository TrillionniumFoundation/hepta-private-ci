"use strict";
function validateRRContinuation(api) {
  const checks=[],raw={};
  function ok(name,condition,details) {
    if(!condition) throw new Error(name+": "+JSON.stringify(details));
    checks.push({name,passed:true,...(details===undefined?{}:{details})});
  }
  function close(a,b,tol=2e-11) {return Math.abs(a-b)<=tol;}
  function maxdiff(A,B) {return Math.max(...A.flat().map((x,i)=>Math.abs(x-B.flat()[i])));}
  let state=0x2739d8ab;
  const random=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296;};
  let analyticError=0,semigroupError=0,massError=0,discountError=0,poissonBound=0;
  for(let k=0;k<64;k++) {
    const a=0.01+2*random(),b=0.01+2*random(),t=4*random(),u=3*random();
    const Q=[[-a,a],[b,-b]],e=Math.exp(-(a+b)*t),d=a+b;
    const exact=[[(b+a*e)/d,a*(1-e)/d],[b*(1-e)/d,(a+b*e)/d]];
    const p=api.transition(Q,t);
    analyticError=Math.max(analyticError,maxdiff(p.matrix,exact));
    poissonBound=Math.max(poissonBound,p.poissonTailBound);
    semigroupError=Math.max(semigroupError,maxdiff(api.transition(Q,t+u).matrix,
      api.multiply(p.matrix,api.transition(Q,u).matrix)));
    massError=Math.max(massError,...p.matrix.map(r=>Math.abs(r.reduce((x,y)=>x+y,0)-1)));
    const rho=0.25*random();
    discountError=Math.max(discountError,...api.continueValue(Q,t,[1,1],rho)
      .map(x=>Math.abs(x-Math.exp(-rho*t))));
  }
  ok("two_state_transition_closed_form",analyticError<2e-12,{cases:64,maxAbsoluteError:analyticError});
  ok("semigroup_composition",semigroupError<2e-12,{cases:64,maxAbsoluteError:semigroupError});
  ok("probability_mass",massError<2e-12,{maxAbsoluteError:massError,maxReportedPoissonTail:poissonBound});
  ok("discounted_continuation_mass",discountError<2e-12,{maxAbsoluteError:discountError});
  const scaleBase=[[-.3,.3],[.7,-.7]];
  const baseTransition=api.transition(scaleBase,2).matrix;
  let scaleError=0;
  for(const scale of [1e-15,1e-12,1e-6,1,1e6,1e12,1e15])
    scaleError=Math.max(scaleError,maxdiff(baseTransition,
      api.transition(scaleBase.map(row=>row.map(x=>x*scale)),2/scale).matrix));
  ok("rate_time_scale_invariance",scaleError<2e-12,
    {scales:7,maxAbsoluteError:scaleError});
  const vector=api.continueValue([[-0.3,0.3],[0.7,-0.7]],2,[1,4],0.1);
  ok("independent_discounted_vector",close(vector[0],1.455865588322065)&&
    close(vector[1],1.7882750634090665),{actual:vector});
  const immediate=vector[0]-.5,atDeadline=api.continueValue([[-.3,.3],[.7,-.7]],2,[.5,3.5],.1)[0];
  ok("loss_timestamp_discount",close(immediate,vector[0]-.5)&&
    close(atDeadline,vector[0]-.5*Math.exp(-.2))&&!close(immediate,atDeadline),
    {immediateLoss:immediate,deadlineLoss:atDeadline});
  const fixture=(budget,loss=.5)=>api.deadlineChoices({budget,evidence:1,resetEvidence:0,
    legs:[{renewDebit:1,emitDebit:2,renewLoss:loss,emitReward:3},
      {renewDebit:1,emitDebit:2,renewLoss:loss,emitReward:1}],
    continuation:s=>s.evidence*((s.renewedMask&1?1.5:0)+(s.renewedMask&2?3:0))});
  raw.budgetFixtures=[1,3,4].map(budget=>({budget,...fixture(budget)}));
  const gold={DD:0,DR:2.5,DE:1,RD:1,RR:3.5,RE:.5,ED:3,ER:2.5};
  const b3=fixture(3);
  ok("atomic_joint_reset_golden",b3.choices.length===8 &&
    b3.choices.every(x=>close(x.value,gold[x.actions]))&&
    b3.best.actions==="RR"&&close(b3.best.value,3.5),{actual:b3.best});
  ok("shared_budget_feasibility",fixture(1).best.actions==="DR"&&
    close(fixture(1).best.value,2.5)&&fixture(1).choices.every(x=>x.charge<=1)&&
    !fixture(1).choices.some(x=>x.actions==="RR"),{actual:fixture(1).best});
  ok("simultaneous_outputs_use_pre_reset_evidence",fixture(4).best.actions==="EE"&&
    close(fixture(4).best.value,4)&&fixture(4).best.next.evidence===0,{actual:fixture(4).best});
  ok("shock_precedes_joint_deadline",api.resourceShock(3,2)===1&&
    fixture(api.resourceShock(3,2)).best.actions==="DR",
    {beforeShockValue:fixture(3).best.value,afterShockValue:fixture(1).best.value});
  const fees=Array.from({length:41},(_,i)=>i*.05);
  raw.feeSweep=fees.map(loss=>({loss,value:fixture(3,loss).best.value,
    actions:fixture(3,loss).best.actions,renewals:[...fixture(3,loss).best.actions].filter(x=>x==="R").length}));
  ok("fee_value_envelope_exact",raw.feeSweep.every(x=>close(x.value,Math.max(4.5-2*x.loss,3))));
  ok("fee_value_nonincreasing",raw.feeSweep.every((x,i,a)=>i===0||x.value<=a[i-1].value+1e-12));
  ok("fee_value_convex",raw.feeSweep.every((x,i,a)=>i===0||i===a.length-1||
    a[i-1].value-2*x.value+a[i+1].value>=-1e-12));
  ok("optimal_renewal_exposure_nonincreasing",raw.feeSweep.every((x,i,a)=>i===0||x.renewals<=a[i-1].renewals));
  raw.discrete=[api.directionCase(0),api.directionCase(.8),api.directionCase(.8,"output_cost")];
  ok("continuation_cost_reverses_wrong_direction",raw.discrete[0].action==="wait"&&
    raw.discrete[1].action==="emit"&&raw.discrete[2].action==="wait"&&
    close(raw.discrete[1].waitValue,.85)&&close(raw.discrete[2].waitValue,.7));
  raw.brownian=[api.brownianDirection(0),api.brownianDirection(.8),api.brownianDirection(.8,"output_cost")];
  const independent=[
    api.positiveNormalMean(1.5,Math.sqrt(.08)),
    api.positiveNormalMean(.8,.2),
    api.positiveNormalMean(.7,Math.sqrt(.08))];
  ok("brownian_three_time_closed_form",raw.brownian.every((x,i)=>close(x.waitValue,independent[i],2e-10)),
    {actual:raw.brownian.map(x=>x.waitValue),closedForm:independent});
  ok("brownian_cost_placement_direction",raw.brownian[0].action==="wait"&&
    raw.brownian[1].action==="emit"&&raw.brownian[2].action==="wait");
  const noBudget=api.brownianDirection(.8,"continuation",0);
  const oneBudget=api.directionCase(0,"continuation",1);
  ok("no_unaffordable_output_or_renewal",noBudget.action==="drop"&&
    noBudget.value===0&&oneBudget.expectedRenewals===0&&oneBudget.action==="emit");
  raw.twoDeadlines=[.5,2].map(fee=>({fee,...api.twoDeadlineDecision([{fee,probability:1}])}));
  const actionValues=x=>Object.fromEntries(x.choices.map(c=>[c.actions,c.value]));
  const low=actionValues(raw.twoDeadlines[0]),high=actionValues(raw.twoDeadlines[1]);
  ok("future_fee_enters_current_continuation",
    close(low.R,3.25)&&close(low.E,2.5)&&close(low.D,2.5)&&
    close(high.R,1.75)&&close(high.E,2.5)&&close(high.D,1)&&
    raw.twoDeadlines[0].best.actions==="R"&&raw.twoDeadlines[1].best.actions==="E",
    {lowFee:low,highFee:high});
  raw.lateObservedFee=[.25,.75].map(p=>({highFeeProbability:p,...api.twoDeadlineDecision([
    {fee:.5,probability:1-p},{fee:2,probability:p}])}));
  ok("future_fee_uses_public_prior_not_realized_outcome",
    raw.lateObservedFee.every(x=>{
      const values=actionValues(x),p=x.highFeeProbability;
      return close(values.R,3.25-1.5*p)&&close(values.E,2.5)&&close(values.D,2.5-1.5*p);
    })&&raw.lateObservedFee[0].best.actions==="R"&&raw.lateObservedFee[1].best.actions==="E");
  function forwardPlan(first,secondLow,secondHigh,p,highFee=2) {
    let total=0;
    for(const [fee,probability,second] of [[.5,1-p,secondLow],[highFee,p,secondHigh]]) {
      let budget=2,evidence=1,reward=0,loss=0,firstRetained=0,secondRetained=0;
      if(first!=="D") budget--;
      if(first==="R"){firstRetained=1;loss+=.25;}
      if(first==="E"){reward+=2.5*evidence;evidence=0;}
      if(second!=="D") budget--;
      if(budget<0) return -Infinity;
      if(second==="R"){secondRetained=1;loss+=fee;}
      if(second==="E"){reward+=evidence;evidence=0;}
      total+=probability*(reward-loss+evidence*(firstRetained+3*secondRetained));
    }
    return total;
  }
  raw.forwardEnumeration=[.25,.75].map(p=>{
    let best={value:-Infinity},plans=0;
    for(const first of ["D","R","E"]) for(const low of ["D","R","E"])
      for(const high of ["D","R","E"]) {
        const value=forwardPlan(first,low,high,p);plans++;
        if(value>best.value) best={value,first,low,high};
      }
    return {p,plans,best};
  });
  ok("independent_forward_policy_enumeration",raw.forwardEnumeration.every((x,i)=>
    close(x.best.value,raw.lateObservedFee[i].best.value)&&
    x.best.first===raw.lateObservedFee[i].best.actions),{actual:raw.forwardEnumeration});
  const observed=api.twoDeadlineDecision([{fee:.5,probability:.75},{fee:4,probability:.25}]);
  let adaptive=-Infinity,precommitted=-Infinity,lowOnly=-Infinity,highOnly=-Infinity;
  for(const first of ["D","R","E"]) for(const low of ["D","R","E"])
    for(const high of ["D","R","E"]) {
      adaptive=Math.max(adaptive,forwardPlan(first,low,high,.25,4));
      if(low===high) precommitted=Math.max(precommitted,forwardPlan(first,low,high,.25,4));
      lowOnly=Math.max(lowOnly,forwardPlan(first,low,high,0,4));
      highOnly=Math.max(highOnly,forwardPlan(first,low,high,1,4));
    }
  const clairvoyant=.75*lowOnly+.25*highOnly;
  raw.informationTiming={distribution:[{fee:.5,probability:.75},{fee:4,probability:.25}],
    actual:observed.best,properForward:adaptive,forcedFuturePrecommitment:precommitted,
    impermissibleCurrentClairvoyance:clairvoyant};
  ok("observation_order_max_expectation",observed.best.actions==="R"&&
    close(observed.best.value,2.625)&&close(adaptive,2.625)&&
    close(precommitted,2.5)&&close(clairvoyant,3.0625),raw.informationTiming);
  const swapped=budget=>api.deadlineChoices({budget,evidence:1,resetEvidence:0,
    legs:[{renewDebit:1,emitDebit:2,renewLoss:.5,emitReward:1},
      {renewDebit:1,emitDebit:2,renewLoss:.5,emitReward:3}],
    continuation:s=>s.evidence*((s.renewedMask&1?3:0)+(s.renewedMask&2?1.5:0))});
  ok("joint_leg_permutation_invariance",[1,3,4].every(b=>{
    const orig=fixture(b),rev=swapped(b),by=new Map(orig.choices.map(x=>[x.actions,x.value]));
    return close(orig.best.value,rev.best.value)&&rev.choices.length===orig.choices.length&&
      rev.choices.every(x=>close(x.value,by.get([...x.actions].reverse().join(""))));
  }));
  const step=1e-5,slopes=[.5,1].map(fee=>
    (fixture(3,fee+step).best.value-fixture(3,fee-step).best.value)/(2*step));
  ok("piecewise_loss_sensitivity_away_from_ties",close(slopes[0],-2,1e-8)&&close(slopes[1],0,1e-8),
    {actual:slopes,tieExcluded:.75});
  const invalid=[
    ()=>api.transition([[1,-1],[0,0]],1),
    ()=>api.transition([[0,1e-13],[0,0]],1),
    ()=>api.transition([[-1e-13,2e-13],[0,0]],1e13),
    ()=>api.transition([[-1,2],[0,0]],1),
    ()=>api.transition([[-1,1],[0,0]],-1),
    ()=>api.transition([[-1,1],[0,0]],Infinity),
    ()=>api.transition([[-100,100],[0,0]],1e6),
    ()=>api.continueValue([[-1,1],[0,0]],1,[1,NaN]),
    ()=>api.deadlineChoices({budget:-1,evidence:1,resetEvidence:0,legs:[],continuation:()=>0}),
    ()=>api.deadlineChoices({budget:1,evidence:1,resetEvidence:0,
      legs:[{renewDebit:-1,emitDebit:1,renewLoss:0,emitReward:1}],continuation:()=>0}),
    ()=>api.deadlineChoices({budget:1,evidence:1,resetEvidence:0,
      legs:[{renewDebit:1,emitDebit:1,renewLoss:0,emitReward:1}],continuation:()=>NaN}),
    ()=>api.resourceShock(1,-1),
    ()=>api.brownianDirection(-1),
    ()=>api.directionCase(.5,"unknown"),
    ()=>api.twoDeadlineDecision([{fee:1,probability:.4}]),
    ()=>api.twoDeadlineDecision([{fee:1,probability:2},{fee:2,probability:-1}]),
    ()=>api.twoDeadlineDecision([{fee:-1,probability:1}])
  ];
  let rejected=0;for(const f of invalid){try{f();}catch{rejected++;}}
  ok("invalid_inputs_fail_closed",rejected===invalid.length,{rejected,total:invalid.length});
  return {schema:"rrsnn.v3.continuation-primitive.validation.v1",allPassed:true,
    scope:"Finite CTMC and finite decision-time mechanism validation; not neural training, target-host execution, or production acceptance.",
    checks,raw};
}
if(typeof module!=="undefined") module.exports={validateRRContinuation};
if(typeof require!=="undefined" && require.main===module) {
  console.log(JSON.stringify(validateRRContinuation(require("./continuation_operator.cjs")),null,2));
}
