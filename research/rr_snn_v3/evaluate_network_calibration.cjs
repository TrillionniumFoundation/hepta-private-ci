"use strict";
/* Frozen-model, free-running synthetic diagnostics. No fitting or acceptance test. */
const NetworkCalibration = (() => { const check=(ok,message)=>{if(!ok)throw new Error(message);};
  const clone=x=>JSON.parse(JSON.stringify(x)); const freeze=x=>{if(x&&typeof x==="object"){Object.values(x).forEach(freeze);Object.freeze(x);}return x;};
  const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==="object"? Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
  const protocol=freeze({ schema:"rrsnn.v3.network-generation-protocol.v1",
    id:"rrsnn-v3-fixed-fit-free-generation-1", learningProtocolFreeze:"16ecf52b7faaa43e9ab0612cc22b5dd35345f063",
    fittedArtifact:{file:"network_learning_results.json",weightsField:"learnedWeights",
      expectedWeights:[[0.3775523523043047,0.27529061923455456,0.5737585774315472,-0.09478794645271761,0.01284951686661228],
        [0.05657995194232138,-0.1340277200480365,0.37582542124719326,-0.0673596342688132,0.4374257174090902]], sha256RequiredInCliOutput:true},
    teacherWeights:[[.4,.35,.45,-.25,.3],[.2,-.25,.35,-.2,.25]], horizon:4,units:2,pulseDebit:1,pressureMode:"full",
    initialBudgetPerUnit:6,maximumAddedPerUnit:1,maximumPhysicalPulsesPerUnit:7,maximumNetworkPhysicalPulses:14,
    seedStart:60000,episodes:1024,stratumAssignment:"episode_index_mod_4", strata:[{id:"A0",maturity:[1,3],shock:0},{id:"A2",maturity:[1,3],shock:2},
      {id:"B0",maturity:[2,2],shock:0},{id:"B2",maturity:[2,2],shock:2}],
    sampling:"Same complete-episode seed for teacher and fitted model; each consumes its own event-dependent random stream. No claim of identical event paths.",
    metricNames:["total_physical_pulses","zero_pulse_indicator","terminal_total_budget","terminal_retained_count"],
    retainedDefinition:"Number of obligations with status retained at H-minus, summed over both units; not value-weighted utility.", differenceDirection:"fitted_minus_teacher",
    bootstrap:{draws:10000,seed:700201,confidence:.95,unit:"whole paired two-neuron episode", stratified:true,episodesPerStratum:256,overallStratumWeights:[.25,.25,.25,.25],
      interval:"pointwise percentile with linear interpolation at (B-1)*p", randomGenerator:"avalanche-seeded LCG32 open uniforms",
      trainingUncertaintyIncluded:false}, execution:"Freeze protocol and script before first generation; no model fitting or parameter selection.",
    failedPathRule:"Retain failure records; if any trajectory or invariant fails, do not compute complete-case estimates or bootstrap.", acceptanceThresholds:null,
    completionScope:"R3 generative diagnostic completed only after all planned paths and invariant checks plus the declared estimates succeed; not full calibration acceptance.",
    limitations:["Fixed synthetic teacher and one fitted artifact; not real-data calibration.", "Four summary statistics do not test the full joint path distribution.",
      "H=4 and two units do not establish long-horizon or large-network stability.",
      "Pointwise intervals are not simultaneous or equivalence tests; rare-event bootstrap may be degenerate.",
      "No R4 superiority, real Cell resource, production-owner or independent real-future-window claim."] });
  function validateWeights(w) { check(Array.isArray(w)&&w.length===2&&w.every(row=>Array.isArray(row)&&row.length===5&&row.every(Number.isFinite)),"expected finite 2x5 weights");
  } function random(seed) {
    let x=(seed+0x9e3779b9)>>>0; x=Math.imul(x^(x>>>16),0x85ebca6b);x=Math.imul(x^(x>>>13),0xc2b2ae35);x=(x^(x>>>16))>>>0;
    return ()=>{x=(Math.imul(x,1664525)+1013904223)>>>0;return (x+.5)/4294967296;}; }
  function finiteNumbers(root) { const stack=[root],seen=new Set();
    while(stack.length) { const x=stack.pop();
      if(typeof x==="number"&&!Number.isFinite(x))return false; if(x&&typeof x==="object"&&!seen.has(x)){seen.add(x);for(const value of Object.values(x))stack.push(value);}
    } return true;
  } const nonnegativeInteger=x=>Number.isSafeInteger(x)&&x>=0;
  function inspect(net) { const observation=net.observe(),statistics=net.statistics(),snapshot=net.snapshot(),pulses=net.pulses();
    check(finiteNumbers([observation,statistics,snapshot,pulses]),"nonfinite trajectory state");
    check(observation.time===protocol.horizon&&Array.isArray(observation.units)&&observation.units.length===2,"terminal observation shape/time");
    check(snapshot&&snapshot.network&&Array.isArray(snapshot.network.units)&&snapshot.network.units.length===2,"network snapshot unit contract");
    check(Array.isArray(pulses)&&nonnegativeInteger(observation.pulseCount)&&pulses.length===observation.pulseCount,"network pulse log/count");
    let totalPulses=0,budget=0,retained=0; const unitAudits=[];
    for(let i=0;i<2;i++) { const unit=observation.units[i],cp=snapshot.network.units[i],state=cp.state,cfg=cp.config;
      check(unit&&state&&cfg&&state.now===protocol.horizon&&nonnegativeInteger(unit.budget)&&unit.budget===state.budget&&unit.budget<=cfg.budgetCap,"terminal time and bounded budget");
      check(Number.isFinite(unit.trace)&&state.trace&&Number.isFinite(state.trace.value)&&Number.isFinite(state.trace.time)&&state.clock&&Number.isFinite(state.clock.at)&&Number.isFinite(state.clock.remaining),"finite trace/hazard state");
      check(nonnegativeInteger(unit.spikeCount)&&unit.spikeCount===state.spikeCount,"unit physical pulse count");
      check(cfg.pulseDebit===protocol.pulseDebit,"fixed positive pulse debit"); const l=state.ledger,names=["initial","spentPulse","spentDeadline","removed","added"];
      check(l&&names.every(k=>nonnegativeInteger(l[k])),"resource ledger fields");
      check(unit.budget===l.initial-l.spentPulse-l.spentDeadline-l.removed+l.added,"resource ledger conservation");
      check(l.spentPulse===unit.spikeCount*cfg.pulseDebit,"physical pulse fee conservation");
      check(l.initial===6&&l.added<=1&&unit.spikeCount<=7,"declared finite-horizon resource bound");
      check(state.aborted===false&&nonnegativeInteger(cfg.maxRecords)&&cfg.maxRecords>0&& Array.isArray(state.log)&&state.log.length<=cfg.maxRecords&&
        Array.isArray(state.queue)&&state.queue.length<=4096,"bounded successful runtime state");
      check(Array.isArray(unit.obligations)&&unit.obligations.every(o=>["live","retained","resolved"].includes(o.status)),"terminal obligations");
      const kept=unit.obligations.filter(o=>o.status==="retained").length;
      check(Array.isArray(state.obligations)&&kept===state.obligations.filter(o=>o.status==="retained").length,"retained observation/state count");
      totalPulses+=unit.spikeCount;budget+=unit.budget;retained+=kept; unitAudits.push({budget:unit.budget,spikeCount:unit.spikeCount,ledger:clone(l),
        recordedEvents:state.log.length,maxRecords:cfg.maxRecords,queuedEvents:state.queue.length}); }
    check(totalPulses===observation.pulseCount&&totalPulses<=14,"whole-network pulse accounting and finite-horizon resource bound");
    return {metrics:[totalPulses,Number(totalPulses===0),budget,retained],unitAudits}; }
  function percentile(sorted,p) { const at=(sorted.length-1)*p,lo=Math.floor(at),hi=Math.ceil(at);
    return sorted[lo]+(sorted[hi]-sorted[lo])*(at-lo); }
  function bootstrap(groups,draws=protocol.bootstrap.draws,seed=protocol.bootstrap.seed) { const rng=random(seed),metrics=4,strata=4;
    const all=Array.from({length:metrics},()=>new Float64Array(draws)); const each=Array.from({length:strata},()=>Array.from({length:metrics},()=>new Float64Array(draws)));
    for(let b=0;b<draws;b++) for(let s=0;s<strata;s++) { const rows=groups[s],sum=[0,0,0,0];
      for(let j=0;j<rows.length;j++) { const r=rows[Math.floor(rng()*rows.length)];
        for(let k=0;k<metrics;k++)sum[k]+=r.fitted.metrics[k]-r.teacher.metrics[k]; }
      for(let k=0;k<metrics;k++){each[s][k][b]=sum[k]/rows.length;all[k][b]+=each[s][k][b]/strata;} }
    const interval=x=>{x.sort();return [percentile(x,.025),percentile(x,.975)];}; return {overall:all.map(interval),strata:each.map(a=>a.map(interval))};
  } function point(rows,k) {
    const n=rows.length,teacher=rows.reduce((sum,r)=>sum+r.teacher.metrics[k],0)/n; const fitted=rows.reduce((sum,r)=>sum+r.fitted.metrics[k],0)/n;
    return {episodes:n,teacherMean:teacher,fittedMean:fitted,difference:fitted-teacher}; }
  function evaluateNetworkCalibration(N,E,C,fittedWeights) { validateWeights(fittedWeights);
    check(JSON.stringify(fittedWeights)===JSON.stringify(protocol.fittedArtifact.expectedWeights),"fitted weights differ from frozen artifact");
    check(N&&typeof N.diagnostic==="function","diagnostic API"); const rows=[],failures=[];
    let successfulTrajectories=0; for(let index=0;index<protocol.episodes;index++) {
      const seed=protocol.seedStart+index,stratum=index%4,setting=protocol.strata[stratum]; const row={seed,stratum:setting.id,teacher:null,fitted:null};
      for(const model of ["teacher","fitted"]) { try {
          const weights=model==="teacher"?protocol.teacherWeights:fittedWeights; const net=N.diagnostic(E,C,clone(weights),seed,null,{
            maturity:setting.maturity.slice(),shock:setting.shock,pressureMode:protocol.pressureMode});
          net.runUntil(protocol.horizon);row[model]=inspect(net);successfulTrajectories++;
        } catch(error) {failures.push({seed,stratum:setting.id,model,error:String(error&&error.message||error)});} }
      rows.push(row); }
    const valid=failures.length===0,groups=protocol.strata.map(s=>rows.filter(r=>r.stratum===s.id)); check(groups.every(g=>g.length===256),"stratum allocation");
    let comparisons=null; if(valid) {
      const ci=bootstrap(groups); comparisons=Object.fromEntries(protocol.metricNames.map((name,k)=>[name,{
        overall:{...point(rows,k),pointwise95PercentCI:ci.overall[k]},
        strata:protocol.strata.map((s,j)=>({stratum:s.id,...point(groups[j],k),pointwise95PercentCI:ci.strata[j][k]})) }]));
    } return {
      schema:"rrsnn.v3.network-generation-results.v1",protocolId:protocol.id, teacherWeights:clone(protocol.teacherWeights),fittedWeights:clone(fittedWeights),
      learningProtocolFreeze:protocol.learningProtocolFreeze,fittedArtifactSha256:null, execution:{seedStart:protocol.seedStart,seedEnd:protocol.seedStart+protocol.episodes-1,
        episodesPerModel:protocol.episodes,attemptedTrajectories:2*protocol.episodes,successfulTrajectories, observedHorizon:protocol.horizon,invariantsPassed:valid,failures},
      comparisons,bootstrap:clone(protocol.bootstrap), generativeDiagnosticCompleted:valid,calibrationAcceptanceAssessed:false,
      fullCalibrationPassed:null,status:valid?"bounded_generative_diagnostic_completed":"invalid_or_incomplete_paths",
      statement:valid?"Completed the prespecified synthetic H=4, two-unit free-generation diagnostic; no equivalence, full-distribution calibration, long-run stability or R4 superiority conclusion is assigned.":
        "At least one generation or invariant check failed; comparisons are withheld rather than selecting complete cases.", limitations:clone(protocol.limitations),rows
    }; }
  return {protocol,evaluateNetworkCalibration,canonical}; })();
if(typeof module!=="undefined")module.exports=NetworkCalibration; if(typeof require!=="undefined"&&require.main===module) {
  const fs=require("fs"),path=require("path"),crypto=require("crypto"); {
    const planPath=path.join(__dirname,"network_calibration_protocol.json"); const plan=JSON.parse(fs.readFileSync(planPath,"utf8"));
    if(JSON.stringify(NetworkCalibration.canonical(plan))!==JSON.stringify(NetworkCalibration.canonical(NetworkCalibration.protocol)))
      throw new Error("Declared calibration protocol does not match executable protocol"); const file=process.argv[2]||path.join(__dirname,"network_learning_results.json");
    const bytes=fs.readFileSync(file),fit=JSON.parse(bytes.toString("utf8")); if(fit.protocolFreeze!==NetworkCalibration.protocol.learningProtocolFreeze||
      JSON.stringify(fit.teacherWeights)!==JSON.stringify(NetworkCalibration.protocol.teacherWeights)) throw new Error("Learning result provenance/teacher mismatch");
    const hash=crypto.createHash("sha256").update(bytes).digest("hex"); const result=NetworkCalibration.evaluateNetworkCalibration(require("./delayed_network.cjs"),
      require("./event_runtime.cjs"),require("./continuation_operator.cjs"),fit.learnedWeights); result.fittedArtifactSha256=hash;result.fittedArtifactFile=path.basename(file);
    console.log(JSON.stringify(result));if(!result.generativeDiagnosticCompleted)process.exitCode=2; }
}
