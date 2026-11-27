"use strict";
function validateRREvents(runtime,continuation) {
  const checks=[],raw={};
  const ok=(name,condition,details)=>{if(!condition)throw new Error(name+": "+JSON.stringify(details));checks.push({name,passed:true,details});};
  const clone=x=>JSON.parse(JSON.stringify(x)),close=(a,b,tol=1e-11)=>Math.abs(a-b)<=tol;
  const cfg=(extra={})=>({identity:"rr-events-validation-v1",evidence:[1],
    channels:[{id:"pulse",from:0,to:0,rate:12,spike:true}],resetState:0,
    refractory:.07,traceTau:1,pulseDebit:1,budgetCap:100,horizon:1,maxRecords:1000,...extra});
  const init=(extra={})=>({stateIndex:0,budget:100,seed:710301,obligations:[],events:[],...extra});
  const make=(c=cfg(),i=init(),h={})=>runtime.create(c,i,continuation,h);
  const seedGold=[{seed:0,word:3620793109},{seed:1,word:1634680782},{seed:710301,word:2100265108}];
  ok("versioned_avalanche_seed_golden",runtime.rngAlgorithm==="lcg32-avalanche-seed-v1"&&
    seedGold.every(g=>make(cfg(),init({seed:g.seed})).snapshot().state.rng.word===g.word),{golden:seedGold});
  const one=make();one.runUntil(1);
  const p=one.pulsesSince().pulses,stats=one.statistics(),cp=one.snapshot();
  ok("marked_self_events_and_repeated_physical_spikes",p.length===7&&stats.stochasticEvents===7&&cp.state.stateIndex===0,{count:p.length,times:p.map(x=>x.time)});
  ok("deterministic_refractory_spacing",p.every((x,i)=>!i||x.time-p[i-1].time>=.07-1e-14));
  const active=1-p.reduce((a,x)=>a+Math.min(.07,1-x.time),0);
  const trace=p.reduce((a,x)=>a+Math.exp(-(1-x.time)),0);
  ok("independent_exposure_final_censor_and_path_likelihood",close(stats.regimes[0].exposure[0],active)&&
    close(stats.logLikelihood,7*Math.log(12)-12*active),{active,logLikelihood:stats.logLikelihood});
  ok("actual_spike_trace_and_positive_resource_debit",close(one.observe().trace,trace)&&cp.state.budget===93&&cp.state.ledger.spentPulse===7,{trace,budget:cp.state.budget});
  const split=make();split.runUntil(.123);
  const saved=JSON.parse(JSON.stringify(split.snapshot()));
  const restored=runtime.restore(saved,continuation,{},cfg().identity);
  restored.runUntil(.502);restored.runUntil(1);
  ok("json_checkpoint_segmented_exact_replay",JSON.stringify(restored.snapshot())===JSON.stringify(cp)&&
    JSON.stringify(restored.statistics())===JSON.stringify(stats));
  const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==="object"?
    Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
  const canonicalRestored=runtime.restore(JSON.parse(JSON.stringify(canonical(saved))),continuation,{},cfg().identity);
  canonicalRestored.runUntil(1);
  ok("canonical_json_key_order_preserves_restore",
    JSON.stringify(canonical(canonicalRestored.snapshot()))===JSON.stringify(canonical(cp))&&
    JSON.stringify(canonical(canonicalRestored.statistics()))===JSON.stringify(canonical(stats)));
  const quiet=make(cfg({channels:[{id:"pulse",from:0,to:0,rate:.01,spike:true}]}));
  quiet.runUntil(.1);
  ok("zero_event_censor_likelihood",quiet.observe().spikeCount===0&&close(quiet.statistics().logLikelihood,-.001)&&quiet.snapshot().state.rng.draws===1);
  const blocked=make(cfg({pulseDebit:2,channels:[{id:"pulse",from:0,to:0,rate:1000,spike:true}]}),init({budget:3}));
  blocked.runUntil(1);
  ok("unaffordable_spike_hazard_zero",blocked.observe().spikeCount===1&&blocked.observe().budget===1&&
    blocked.statistics().stochasticEvents===1);
  const o=(id,deadline,loss=0.2)=>({id,deadline,renewDebit:1,renewLoss:loss,emitDebit:0,emitValue:1,status:"live"});
  const during=make(cfg({horizon:.3,refractory:.2,pulseDebit:2,budgetCap:10,
    channels:[{id:"pulse",from:0,to:0,rate:1000,spike:true}]}),
    init({budget:4,obligations:[o("renew",.03),o("drop",.04,100)],
      events:[{time:.01,type:"shock",amount:1},{time:.02,type:"refill",amount:3},{time:.05,type:"control",rates:[0]}]}),
    {continuation:obs=>10*obs.obligations.filter(x=>x.status==="retained").length});
  during.runUntil(.3);
  const dc=during.snapshot(),dl=dc.state.log.filter(x=>x.type==="deadline");
  ok("deadlines_resources_and_controls_continue_during_refractory",dl.length===2&&dl[0].actions==="R"&&dl[1].actions==="D"&&
    dc.state.spikeCount===1&&dc.state.budget===3&&dc.state.ledger.spentDeadline===1,{deadlines:dl,ledger:dc.state.ledger});
  let seenInput=null;
  const ordered=make(cfg({channels:[{id:"pulse",from:0,to:0,rate:0,spike:true}],refractory:.1}),
    init({budget:1,obligations:[{...o("item",.5,1),emitValue:2}],events:[
      {time:.5,type:"input",data:[2]},{time:.5,type:"refill",amount:2},
      {time:.5,type:"control",rates:[10]},{time:.5,type:"shock",amount:1}]}),
    {input:obs=>{seenInput=obs;return [0];}});
  ordered.runUntil(1);
  const at=ordered.snapshot().state.log.filter(x=>x.time===.5);
  ok("deterministic_same_timestamp_order",JSON.stringify(at.map(x=>x.type))===JSON.stringify(["shock","refill","input","control","deadline"])&&seenInput.budget===2,
    {order:at.map(x=>x.type)});
  ok("deadline_emission_is_physical_but_not_stochastic",at[4].spike===true&&at[4].charge===1&&
    ordered.snapshot().state.pulses[0].kind==="deadline"&&ordered.statistics().physicalPulses===ordered.statistics().stochasticEvents+1);
  const shared=make(cfg({channels:[{id:"pulse",from:0,to:0,rate:0,spike:true}]}),
    init({budget:2,obligations:[{...o("a",.5,1),emitValue:3},{...o("b",.5,1),emitValue:1}]}));
  shared.runUntil(1);
  const sj=shared.snapshot().state.log.find(x=>x.type==="deadline");
  ok("one_neuron_joint_deadline_at_most_one_physical_emission",sj.actions==="ED"&&shared.observe().spikeCount===1&&shared.observe().budget===1,{action:sj.actions});
  const terminal=make(cfg({channels:[{id:"pulse",from:0,to:0,rate:0,spike:true}]}),
    init({budget:1,obligations:[o("terminal",.5)],events:[
      {time:1,type:"refill",amount:2},{time:1,type:"control",rates:[100]}]}),
    {continuation:obs=>3*obs.obligations.filter(x=>x.status==="retained").length});
  terminal.runUntil(1);
  const ts=terminal.snapshot().state;
  ok("terminal_left_limit_skips_events_at_horizon",terminal.nextEventTime()===null&&ts.budget===0&&
    ts.cursor===0&&ts.spikeCount===0&&ts.obligations[0].status==="retained"&&
    ts.obligations[0].deadline===1&&ts.log.length===1);
  let observationKeys=[];
  const hooks={input:(obs,data)=>{observationKeys=Object.keys(obs).sort();return [2+data[0]*obs.trace];}};
  const networkCfg=cfg({channels:[{id:"pulse",from:0,to:0,rate:2,spike:true}],refractory:.05});
  const owner=make(networkCfg,init(),hooks),first=owner.nextEventTime();
  owner.runUntil(first);owner.enqueue({time:first+.1,type:"input",data:[1]});
  while(owner.nextEventTime()!==null) owner.runUntil(owner.nextEventTime());
  const direct=make(networkCfg,init({events:[{time:first+.1,type:"input",data:[1]}]}),hooks);direct.runUntil(1);
  ok("owner_next_event_and_positive_delay_injection",JSON.stringify(owner.snapshot())===JSON.stringify(direct.snapshot()));
  ok("hooks_have_no_rng_hazard_or_future_queue",JSON.stringify(observationKeys)===JSON.stringify(
    ["time","stateIndex","evidence","budget","refractoryRemaining","trace","spikeCount","obligations"].sort()),{keys:observationKeys});
  const equal=make(cfg({channels:[{id:"pulse",from:0,to:0,rate:0,spike:true}]}),
    init({events:[{time:0,type:"input",data:[0]},{time:.4,type:"input",data:[1]}]}),{input:()=>[0]});
  equal.runUntil(1);
  const er=equal.statistics().regimes;
  ok("equal_numeric_rates_keep_distinct_feature_regimes",er.length===3&&close(er[0].exposure[0],0)&&
    close(er[1].exposure[0],.4)&&close(er[2].exposure[0],.6)&&equal.snapshot().state.rng.draws===1,{regimes:er});
  const switchedCfg=cfg({evidence:[0,1],channels:[
    {id:"up",from:0,to:1,rate:3,spike:false},{id:"fire",from:1,to:0,rate:5,spike:true}]});
  const switched=make(switchedCfg,init({events:[{time:.2,type:"control",rates:[4,7]},
    {time:.4,type:"shock",amount:1},{time:.6,type:"refill",amount:1}]}));
  switched.runUntil(1);
  const sc=switched.snapshot(),ss=switched.statistics();
  let state=0,budget=100,refUntil=0,rate=[3,5],last=0,hazard=0,logRates=0,eventCount=0;
  function integrate(t) {for(let j=0;j<2;j++) if(last>=refUntil&&state===switchedCfg.channels[j].from&&
    (!switchedCfg.channels[j].spike||budget>=1)) hazard+=rate[j]*(t-last);last=t;}
  for(const row of sc.state.log) {
    integrate(row.time);budget=row.budget;
    if(row.type==="control"||row.type==="input") rate=ss.regimes[row.regime].rates;
    if(row.type==="jump") {logRates+=Math.log(row.rate);eventCount++;state=row.to;
      if(row.spike) refUntil=row.time+switchedCfg.refractory;}
  }
  integrate(1);
  ok("independent_all_channel_path_score_with_switch_and_censor",close(hazard,ss.hazard)&&close(logRates-hazard,ss.logLikelihood)&&
    eventCount===ss.stochasticEvents,{hazard,logLikelihood:ss.logLikelihood,eventCount});
  const changes=[
    x=>{x.unexpected=true;},x=>{x.state.rng.word=-1;},x=>{x.state.budget++;},
    x=>{x.state.clock.remaining=-1;},x=>{x.state.trace.value+=1;},
    x=>{x.state.regimes[0].counts[0]++;},x=>{x.state.log[0].extra=true;},
    x=>{x.state.rates[0]=NaN;}
  ];
  let rejected=0;
  for(const change of changes) {const bad=clone(saved);change(bad);try{runtime.restore(bad,continuation,{},cfg().identity);}catch{rejected++;}}
  try{runtime.restore(saved,continuation,{},"wrong-identity");}catch{rejected++;}
  try{make(cfg({pulseDebit:0}));}catch{rejected++;}
  try{owner.enqueue({time:owner.observe().time,type:"input",data:[1]});}catch{rejected++;}
  ok("invalid_restore_and_event_inputs_fail_closed",rejected===changes.length+3,{rejected});
  const limited=make(cfg({maxRecords:1}));let capped=false,aborted=false;
  try{limited.runUntil(1);}catch{capped=true;}try{limited.snapshot();}catch{aborted=true;}
  ok("bounded_work_abort_cannot_publish_checkpoint",capped&&aborted);
  let countSum=0,zero=0,terminalOnes=0;
  const samples=2048,poissonCfg=cfg({refractory:0,channels:[{id:"pulse",from:0,to:0,rate:3.5,spike:true}]}),
    chainCfg=cfg({refractory:0,evidence:[0,1],channels:[
      {id:"up",from:0,to:1,rate:.7,spike:false},{id:"down",from:1,to:0,rate:1.3,spike:false}]});
  for(let k=0;k<samples;k++) {
    const seed=Math.imul(k+801001,0x9e3779b1)>>>0;
    const a=make(poissonCfg,init({seed}));a.runUntil(1);const count=a.observe().spikeCount;countSum+=count;zero+=Number(count===0);
    const b=make(chainCfg,init({seed}));b.runUntil(1);terminalOnes+=b.observe().stateIndex;
  }
  const mean=countSum/samples,p0=zero/samples,endpoint=terminalOnes/samples,truth=.35*(1-Math.exp(-2));
  ok("marked_self_poisson_distribution_reference",Math.abs(mean-3.5)<6*Math.sqrt(3.5/samples)&&
    Math.abs(p0-Math.exp(-3.5))<6*Math.sqrt(Math.exp(-3.5)*(1-Math.exp(-3.5))/samples),{samples,mean,p0,truthMean:3.5});
  ok("ordinary_ctmc_endpoint_closed_form_reference",Math.abs(endpoint-truth)<6*Math.sqrt(truth*(1-truth)/samples),{samples,endpoint,truth});
  raw.repeatedPulseTimes=p.map(x=>x.time);raw.statistics=stats;raw.resourceDuringRefractory=dc.state.ledger;
  return {schema:"rrsnn.v3.event-runtime.validation.v1",allPassed:true,checks,raw,
    scope:"Marked finite-CTMC reference with deterministic refractory; no Brownian, neural superiority, production host or Cell validation."};
}
if(typeof module!=="undefined") module.exports={validateRREvents};
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(validateRREvents(require("./event_runtime.cjs"),require("./continuation_operator.cjs")),null,2));
