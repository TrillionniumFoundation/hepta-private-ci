"use strict";
function validateRRNetwork(N,M,C) {
  const checks=[],assert=(ok,name,detail)=>{checks.push({name,passed:!!ok,detail});
    if(!ok)throw new Error(name);},clone=x=>JSON.parse(JSON.stringify(x));
  const teacher=[[.4,.35,.45,-.25,.3],[.2,-.25,.35,-.2,.25]];
  const a=N.diagnostic(M,C,teacher,9001);a.runUntil(4);
  assert(a.pulses().length>=2&&new Set(a.pulses().map(x=>x.from)).size===2,
    "actual recurrent network emits from both units",a.pulses());
  const b=N.diagnostic(M,C,teacher,9001);
  for(const t of [.17,.8,1.49,1.5,2.05,2.99,4])b.runUntil(t);
  assert(JSON.stringify(a.snapshot())===JSON.stringify(b.snapshot()),
    "observation slicing preserves complete network state",null);
  const partial=N.diagnostic(M,C,teacher,9001);partial.runUntil(1.73);
  const cp=clone(partial.snapshot());
  const restored=N.diagnostic(M,C,teacher,9001,cp);restored.runUntil(4);
  assert(JSON.stringify(a.snapshot())===JSON.stringify(restored.snapshot()),
    "restore retains pending axonal inputs and every neuron clock",null);
  const zero=N.diagnostic(M,C,[[0,0,0,0,0],[0,0,0,0,0]],9003);
  zero.runUntil(4);
  const zeroRecords=zero.records().flat();
  assert(new Set(zeroRecords.map(r=>JSON.stringify(r.features))).size>2&&
    zeroRecords.every(r=>r.features.length===5),"equal rates retain distinct feature regimes",
    {records:zeroRecords.length,uniqueFeatures:new Set(zeroRecords.map(r=>JSON.stringify(r.features))).size});
  const pairs={};
  for(const mode of ["full","mean"]) {
    const pair=[[1,3],[2,2]].map(maturity=>N.diagnostic(M,C,teacher,9010,null,
      {maturity,shock:2,pressureMode:mode}));
    const physical=net=>net.observe().units.map(({time,stateIndex,evidence,budget,
      refractoryRemaining,trace,spikeCount})=>({time,stateIndex,evidence,budget,refractoryRemaining,trace,spikeCount}));
    assert(JSON.stringify(physical(pair[0]))===JSON.stringify(physical(pair[1])),
      mode+" counterfactual has identical physical initial state",null);
    pair.forEach(net=>net.runUntil(0));
    const initialRates=pair.map(net=>net.statistics().map(u=>u.regimes.at(-1).rates[1]));
    pair.forEach(net=>net.runUntil(.99));
    pairs[mode]={initialRates,pulses:pair.map(net=>net.pulses())};
  }
  assert(pairs.full.initialRates[0].some((x,i)=>x!==pairs.full.initialRates[1][i])&&
    JSON.stringify(pairs.mean.initialRates[0])===JSON.stringify(pairs.mean.initialRates[1]),
    "full deadline structure changes rates while mean-only ablation cannot",pairs);
  assert(JSON.stringify(pairs.mean.pulses[0])===JSON.stringify(pairs.mean.pulses[1]),
    "equal-rate ablation keeps the same actual pre-deadline paths",null);
  const ordered=x=>Array.isArray(x)?x.map(ordered):x&&typeof x==="object"?
    Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])])):x;
  const canonicalRestored=N.diagnostic(M,C,teacher,9001,ordered(cp));canonicalRestored.runUntil(4);
  assert(JSON.stringify(ordered(canonicalRestored.snapshot()))===JSON.stringify(ordered(a.snapshot())),
    "canonical JSON key order preserves complete network restore",null);
  const record=a.records().flat(),w=[.1,-.2,.3,.05,-.1],v=N.likelihood(w,record,.01);
  const errors=w.map((_,j)=>{
    const lo=w.slice(),hi=w.slice();lo[j]-=1e-5;hi[j]+=1e-5;
    return (N.likelihood(hi,record,.01).loss-N.likelihood(lo,record,.01).loss)/2e-5-v.gradient[j];
  });
  assert(Math.max(...errors.map(Math.abs))<2e-7,"coupled-path censored score vs finite differences",errors);
  const early=N.diagnostic(M,C,teacher,9002);early.runUntil(.8);
  assert(early.records().flat().some(r=>r.count===0&&r.exposure>0),
    "unfired censored intervals retain likelihood exposure",early.records());
  const fullScore=early.records().reduce((sum,rows,i)=>sum+rows.reduce((s,r)=>s+r.count-Math.exp(
    teacher[i].reduce((z,x,j)=>z+x*r.features[j],0))*r.exposure,0),0);
  assert(Number.isFinite(fullScore),"censored score is finite",fullScore);
  const rejected=[];
  function rejects(label,fn){try{fn();rejected.push({label,rejected:false});}
    catch{rejected.push({label,rejected:true});}}
  let bad=clone(cp);bad.network.cursors[0]++;
  rejects("pulse cursor",()=>N.diagnostic(M,C,teacher,9001,bad));
  bad=clone(cp);bad.network.edges[0].delay=0;
  rejects("altered graph",()=>N.diagnostic(M,C,teacher,9001,bad));
  bad=clone(cp);bad.weights[0][0]+=.1;
  rejects("changed weights",()=>N.diagnostic(M,C,teacher,9001,bad));
  bad=clone(cp);bad.network.pulses.push({from:0,ordinal:999,pulse:{time:.1,kind:"fake",channel:"pulse"}});
  rejects("forged pulse history",()=>N.diagnostic(M,C,teacher,9001,bad));
  bad=clone(cp);bad.futureOracle=true;
  rejects("unknown checkpoint key",()=>N.diagnostic(M,C,teacher,9001,bad));
  rejects("out of horizon",()=>N.diagnostic(M,C,teacher,9001).runUntil(4.1));
  rejects("invalid path exposure",()=>N.likelihood([0],[{features:[1],exposure:0,count:1}]));
  rejects("log-rate overflow",()=>N.likelihood([100],[{features:[1],exposure:1,count:0}]));
  rejects("aggregate objective overflow",()=>N.likelihood([0],[{features:[1],exposure:1e308,count:0},
    {features:[1],exposure:1e308,count:0}]));
  assert(rejected.every(x=>x.rejected),"nine invalid path or restore cases reject",rejected);
  return {schema:"rr-delayed-network-validation-1",passed:checks.length,checks,
    physicalPulses:a.pulses().length,regimeCounts:a.statistics().map(x=>x.regimes.length),
    claims:{realPhysicalPulses:true,strictlyPositiveAxonalDelays:true,
      fixedObservationGrid:false,completePathScore:true,productionOwner:false}};
}
if(typeof module!=="undefined")module.exports=validateRRNetwork;
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(validateRRNetwork(require("./delayed_network.cjs"),
    require("./event_runtime.cjs"),require("./continuation_operator.cjs")),null,2));
