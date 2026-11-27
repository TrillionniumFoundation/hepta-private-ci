"use strict";
/* Bounded reference replay for the actual two-unit delayed-network diagnostic. */
const RRNetworkJointReplay=(()=>{
  const SCHEMA="rrsnn.network-joint-checkpoint.v1",ZERO="0".repeat(64);
  const check=(ok,message)=>{if(!ok)throw new Error(message);};
  const keys=(x,names,label)=>check(x&&typeof x==="object"&&!Array.isArray(x)&&
    Object.keys(x).sort().join("|")===names.split(" ").sort().join("|"),label+" fields");
  const integer=(x,min,max,label)=>check(Number.isSafeInteger(x)&&x>=min&&x<=max,label);
  const finite=(x,min,max,label)=>check(Number.isFinite(x)&&x>=min&&x<=max,label);
  const hash=x=>check(typeof x==="string"&&/^[0-9a-f]{64}$/.test(x),"digest");
  const id=x=>check(typeof x==="string"&&/^[A-Za-z0-9._:/-]{1,128}$/.test(x),"identity");
  function weightsValid(w) {
    check(Array.isArray(w)&&w.length===2,"two weight rows");
    for(const row of w)check(Array.isArray(row)&&row.length===5&&row.every(Number.isFinite),"five finite weights");
  }
  function scenarioValid(s) {
    keys(s,"maturity shock pressureMode","scenario");
    check(Array.isArray(s.maturity)&&s.maturity.length===2&&
      ((s.maturity[0]===1&&s.maturity[1]===3)||(s.maturity[0]===2&&s.maturity[1]===2)),"maturity profile");
    check((s.shock===0||s.shock===2)&&s.pressureMode==="full","scenario profile");
  }
  function shape(J,cp) {
    J.canonical(cp);keys(cp,"schema seed weights scenario features network","network snapshot");
    check(cp.schema==="rr-network-diagnostic-1","diagnostic schema");
    integer(cp.seed,0,0xffffffff,"seed");weightsValid(cp.weights);scenarioValid(cp.scenario);
    const n=cp.network;
    keys(n,"schema identity horizon time steps maxSteps edges cursors pulses units","network");
    check(n.schema==="rr-delayed-network-1"&&n.horizon===4,"network profile");id(n.identity);
    finite(n.time,0,4,"network time");integer(n.maxSteps,1,100000,"step cap");
    integer(n.steps,0,n.maxSteps,"step count");
    check(Array.isArray(n.units)&&n.units.length===2,"unit count");
    check(Array.isArray(n.cursors)&&n.cursors.length===2,"pulse cursors");
    check(Array.isArray(cp.features)&&cp.features.length===2,"feature units");
    for(let i=0;i<2;i++) {
      J.shape(n.units[i]);check(n.units[i].state.now===n.time&&n.units[i].config.horizon===4,"unit/global clock");
      integer(n.cursors[i],0,n.units[i].state.spikeCount,"pulse cursor");
      check(Array.isArray(cp.features[i])&&cp.features[i].length===n.units[i].state.regimes.length,"feature regimes");
      cp.features[i].forEach(v=>check(Array.isArray(v)&&v.length===5&&v.every(Number.isFinite),"feature vector"));
    }
    check(Array.isArray(n.edges)&&n.edges.length===2,"edge count");
    for(const e of n.edges) {
      keys(e,"from to delay","edge");integer(e.from,0,1,"edge source");integer(e.to,0,1,"edge target");
      finite(e.delay,Number.MIN_VALUE,4,"positive delay");
    }
    check(Array.isArray(n.pulses)&&n.pulses.length===n.cursors[0]+n.cursors[1],"network pulse count");
    for(const p of n.pulses) {
      keys(p,"from ordinal pulse","network pulse");integer(p.from,0,1,"pulse source");
      integer(p.ordinal,0,n.units[p.from].state.spikeCount,"pulse ordinal");
      keys(p.pulse,"time kind channel","physical pulse");finite(p.pulse.time,0,n.time,"pulse time");
      check(["jump","deadline"].includes(p.pulse.kind)&&
        (p.pulse.channel===null||typeof p.pulse.channel==="string"),"pulse mark");
    }
  }
  function bind(options) {
    keys(options,"Joint Engine Continuation Network weights seed scenario sourceHashes model","options");
    const {Joint:J,Engine:E,Continuation:C,Network:N}=options;
    const copy=x=>JSON.parse(J.canonical(x)),same=(a,b)=>J.canonical(a)===J.canonical(b);
    const weights=copy(options.weights),seed=options.seed,scenario=copy(options.scenario);
    weightsValid(weights);integer(seed,0,0xffffffff,"seed");scenarioValid(scenario);
    keys(options.sourceHashes,"engine continuation network journal adapter","source hashes");
    Object.values(options.sourceHashes).forEach(hash);
    const fresh=()=>N.diagnostic(E,C,copy(weights),seed,null,copy(scenario));
    const initial=fresh().snapshot();shape(J,initial);
    check(same(initial.weights,weights)&&initial.seed===seed&&same(initial.scenario,scenario)&&initial.network.time===0,"genesis identity");
    const binding={source:copy(options.sourceHashes),model:J.digest("rrsnn.network-model.v1",options.model),
      weights:J.digest("rrsnn.network-weights.v1",weights),seed,scenario:J.digest("rrsnn.network-scenario.v1",scenario),
      graph:J.digest("rrsnn.network-graph.v1",initial.network.edges),identity:initial.network.identity};
    function identity(cp) {
      check(cp.seed===seed&&same(cp.weights,weights)&&same(cp.scenario,scenario),"snapshot seed/weights/scenario identity");
      check(cp.network.identity===initial.network.identity&&cp.network.maxSteps===initial.network.maxSteps&&
        same(cp.network.edges,initial.network.edges),"graph/runtime identity");
    }
    function pack(snapshot,sequence,predecessor) {
      integer(sequence,0,1024,"journal sequence");hash(predecessor);
      check((sequence===0)===(predecessor===ZERO),"predecessor profile");
      shape(J,snapshot);identity(snapshot);
      const payload={binding:copy(binding),sequence,predecessor,time:snapshot.network.time,snapshot:copy(snapshot)};
      return {schema:SCHEMA,authority:"none",payload,digest:J.digest(SCHEMA,payload)};
    }
    const genesis=pack(initial,0,ZERO);
    function unpack(cp,expectedDigest) {
      J.canonical(cp);keys(cp,"schema authority payload digest","envelope");
      check(cp.schema===SCHEMA&&cp.authority==="none","envelope profile");
      hash(cp.digest);if(expectedDigest!==undefined)check(cp.digest===expectedDigest,"external digest mismatch");
      const p=cp.payload;keys(p,"binding sequence predecessor time snapshot","payload");
      check(same(p.binding,binding),"source/model/weights/seed/scenario identity");
      check(J.digest(SCHEMA,p)===cp.digest,"checksum mismatch");
      integer(p.sequence,0,1024,"journal sequence");hash(p.predecessor);
      check((p.sequence===0)===(p.predecessor===ZERO),"predecessor profile");
      shape(J,p.snapshot);identity(p.snapshot);
      check(p.time===p.snapshot.network.time,"envelope clock");
      // Reference work is bounded by the diagnostic runtime's horizon/work caps.
      // Replaying from genesis binds dynamic queues and feature history, not just hashes.
      const replay=fresh();if(p.sequence>0)replay.runUntil(p.time);
      check(same(replay.snapshot(),p.snapshot),"deterministic network replay mismatch");
      if(p.sequence===0)check(same(cp,genesis),"genesis mismatch");
      const runtime=N.diagnostic(E,C,copy(weights),seed,copy(p.snapshot),copy(scenario));
      check(same(runtime.snapshot(),p.snapshot),"network restore changed state");return runtime;
    }
    return {genesis:copy(genesis),binding:copy(binding),unpack,
      next(cp,time) {
        finite(time,cp.payload.time,4,"stale/invalid time");
        integer(cp.payload.sequence+1,1,1024,"journal sequence");
        const runtime=unpack(cp);runtime.runUntil(time);
        return pack(runtime.snapshot(),cp.payload.sequence+1,cp.digest);
      }};
  }
  return {SCHEMA,bind,shape};
})();
if(typeof module!=="undefined")module.exports=RRNetworkJointReplay;
