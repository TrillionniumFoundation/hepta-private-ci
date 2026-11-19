"use strict";
/* Uses the actual network module; no surrogate network or filesystem proof. */
function validateNetworkReplay(R,J,N,E,C,sources) {
  const assert=(ok,message)=>{if(!ok)throw new Error(message);};
  const clone=x=>JSON.parse(J.canonical(x)),same=(a,b)=>J.canonical(a)===J.canonical(b);
  const eq=(a,b,message)=>assert(same(a,b),message);
  const rejections=[];
  function reject(name,fn,reason) {
    let error;try{fn();}catch(e){error=e.message;}
    assert(error&&(!reason||error.includes(reason)),"wrong/absent rejection "+name+": "+error);
    rejections.push({name,error});
  }
  const weights=[[0.4,0.35,0.45,-0.25,0.3],[0.2,-0.25,0.35,-0.2,0.25]],seed=9001;
  const scenario={maturity:[2,2],shock:2,pressureMode:"full"},model={name:"fixed-delayed-network",version:1};
  const sourceHashes=Object.fromEntries(Object.entries(sources).map(([k,v])=>[k,J.sha256(v)]));
  const options={Joint:J,Engine:E,Continuation:C,Network:N,weights,seed,scenario,sourceHashes,model};
  const A=R.bind(options),g=A.genesis,whole=N.diagnostic(E,C,clone(weights),seed,null,clone(scenario));
  whole.runUntil(4);
  const final=whole.snapshot(),stats=whole.statistics(),records=whole.records(),pulses=whole.pulses();
  assert(final.network.pulses.length===6,"fixed fixture physical pulse count");
  assert(final.network.units.every(u=>u.state.spikeCount>0),"both units must actually emit");
  assert(final.network.units.reduce((n,u)=>n+u.state.spikeCount,0)===final.network.pulses.length,"pulse totals");
  const pendingTime=1.9,pending=A.next(g,pendingTime),network=pending.payload.snapshot.network;
  const deliveries=network.units.map((u,to)=>{
    const queueIndex=u.state.queue.findIndex((e,i)=>i>=u.state.cursor&&e.type==="input"&&e.seq>=7&&e.time>pendingTime);
    assert(queueIndex>=0,"both units must contain a pending axonal delivery");
    const queued=u.state.queue[queueIndex],edge=network.edges.find(e=>e.to===to);
    const pulse=network.pulses.find(p=>p.from===edge.from&&p.pulse.time+edge.delay===queued.time);
    assert(pulse,"pending queue must match an actual emitted pulse");
    return {from:edge.from,to,queueIndex,deliveryTime:queued.time,pulseTime:pulse.pulse.time};
  });
  const selected=deliveries[0];
  const restores=[];
  for(const stop of [0,0.73,1.5,1.73,pendingTime,2.25,3.8]) {
    const cp=A.next(g,stop),resumed=A.unpack(JSON.parse(J.canonical(cp)),cp.digest);
    resumed.runUntil(4);
    eq(resumed.snapshot(),final,"network continuation state at "+stop);
    eq(resumed.statistics(),stats,"network continuation statistics at "+stop);
    eq(resumed.records(),records,"network continuation records at "+stop);
    eq(resumed.pulses(),pulses,"network continuation physical pulses at "+stop);
    restores.push({stop,completeStateExact:true,statisticsExact:true,recordsExact:true,pulsesExact:true,
      pendingDelivery:stop===pendingTime,checkpointDigest:cp.digest});
  }
  function stores() {
    const journal=new J.MemoryJournal(g),witness=new J.MemoryWitness(g.digest,J.anchor(g));
    const lease={owner:"network.a",generation:journal.claim("network.a",0)};
    return {journal,witness,lease,owner:J.open(A,journal,witness,lease,J.anchor(g))};
  }
  const faultResults=[],middle=(pendingTime+4)/2;
  for(const fault of ["before_append","torn_tail","after_append","after_witness"]) {
    const s=stores(),first=s.owner.commit(J.anchor(g),{sequence:1,time:pendingTime});
    const expected=J.anchor(first),request={sequence:2,time:middle};
    reject("crash_"+fault,()=>s.owner.commit(expected,request,fault),"simulated crash");
    reject("poison_"+fault,()=>s.owner.commit(expected,request),"poisoned owner");
    const journal=J.MemoryJournal.from(clone(s.journal.image())),witness=J.MemoryWitness.from(clone(s.witness.image()));
    const lease={owner:"network.b",generation:journal.claim("network.b",s.lease.generation)};
    const owner=J.open(A,journal,witness,lease,expected),second=owner.commit(expected,request);
    eq(second,A.next(first,middle),"reconciled network checkpoint");
    const before=J.canonical(journal.image());eq(owner.commit(expected,request),second,"retry receipt");
    assert(before===J.canonical(journal.image()),"retry appended duplicate");
    const last=owner.commit(J.anchor(second),{sequence:3,time:4});
    eq(last.payload.snapshot,final,"network crash final state");
    faultResults.push({fault,recovered:true,finalDigest:last.digest,physicalPulses:final.network.pulses.length});
  }
  const reseal=change=>{const cp=clone(pending);change(cp);cp.digest=J.digest(R.SCHEMA,cp.payload);return cp;};
  for(const name of ["engine","continuation","network","journal","adapter"])
    reject("source_"+name,()=>R.bind({...options,sourceHashes:{...sourceHashes,[name]:"0".repeat(64)}}).unpack(pending),"identity");
  reject("model_identity",()=>R.bind({...options,model:{...model,version:2}}).unpack(pending),"identity");
  const otherWeights=clone(weights);otherWeights[0][0]+=0.01;
  reject("weights_identity",()=>R.bind({...options,weights:otherWeights}).unpack(pending),"identity");
  reject("seed_identity",()=>R.bind({...options,seed:seed+1}).unpack(pending),"identity");
  reject("scenario_identity",()=>R.bind({...options,scenario:{...scenario,maturity:[1,3]}}).unpack(pending),"identity");
  reject("graph_resealed",()=>A.unpack(reseal(cp=>cp.payload.snapshot.network.edges[0].delay+=0.01)),"graph/runtime identity");
  reject("feature_resealed",()=>A.unpack(reseal(cp=>cp.payload.snapshot.features[0][0][0]+=0.1)),"deterministic network replay mismatch");
  const nullspace=reseal(cp=>{
    const v=cp.payload.snapshot.features[0][0],before=v.reduce((sum,x,k)=>sum+x*weights[0][k],0);
    v[0]+=weights[0][1]*0.01;v[1]-=weights[0][0]*0.01;
    assert(Math.abs(v.reduce((sum,x,k)=>sum+x*weights[0][k],0)-before)<1e-12,"not a weight-nullspace perturbation");
  });
  reject("feature_nullspace_resealed",()=>A.unpack(nullspace),"deterministic network replay mismatch");
  reject("dynamic_queue_resealed",()=>A.unpack(reseal(cp=>{
    const e=cp.payload.snapshot.network.units[selected.to].state.queue[selected.queueIndex];e.data[0]=(e.data[0]||0)+0.125;
  })),"deterministic network replay mismatch");
  reject("residual_hazard_resealed",()=>A.unpack(reseal(cp=>cp.payload.snapshot.network.units[0].state.clock.remaining+=0.01)),
    "deterministic network replay mismatch");
  reject("unknown_payload_field",()=>A.unpack(reseal(cp=>cp.payload.cache={})),"fields");
  reject("unknown_unit_field",()=>A.unpack(reseal(cp=>cp.payload.snapshot.network.units[0].state.cache={})),"fields");
  reject("budget_resealed",()=>A.unpack(reseal(cp=>{const s=cp.payload.snapshot.network.units[0].state;s.budget+=s.budget===0?1:-1;})),"ledger conservation");
  reject("nonfinite_feature",()=>{const cp=clone(pending);cp.payload.snapshot.features[0][0][0]=NaN;A.unpack(cp);},"nonfinite");
  reject("external_digest",()=>A.unpack(pending,"0".repeat(64)),"external digest");
  reject("stale_time",()=>A.next(pending,pendingTime/2),"stale/invalid time");
  const limit=clone(pending);limit.payload.sequence=1024;limit.digest=J.digest(R.SCHEMA,limit.payload);A.unpack(limit);
  reject("sequence_overflow",()=>A.next(limit,pendingTime),"journal sequence");
  reject("invalid_predecessor",()=>A.unpack(reseal(cp=>cp.payload.predecessor="0".repeat(64))),"predecessor profile");
  const s=stores(),first=s.owner.commit(J.anchor(g),{sequence:1,time:pendingTime});
  const second=s.owner.commit(J.anchor(first),{sequence:2,time:middle});
  reject("changed_old_tick",()=>s.owner.commit(J.anchor(g),{sequence:1,time:middle}),"stale/changed tick");
  reject("stale_head",()=>s.owner.commit(J.anchor(g),{sequence:3,time:4}),"stale head/sequence");
  const truncated=s.journal.image();truncated.frames.pop();
  reject("acknowledged_rollback",()=>J.open(A,J.MemoryJournal.from(truncated),s.witness,s.lease,J.anchor(second)),"acknowledged rollback");
  const forged=s.journal.image(),frame=forged.frames[0];
  frame.checkpoint=clone(nullspace);
  const {digest:ignored,...body}=frame;frame.digest=J.digest("rrsnn.journal-frame.v1",body);
  reject("rehashed_network_journal",()=>J.open(A,J.MemoryJournal.from(forged),s.witness,s.lease,J.anchor(first)),"deterministic replay mismatch");
  const newer={owner:"network.b",generation:s.journal.claim("network.b",s.lease.generation)};
  reject("old_writer_fenced",()=>s.owner.commit(J.anchor(second),{sequence:3,time:4}),"stale writer fence");
  J.open(A,s.journal,s.witness,newer,J.anchor(second));
  return {schema:"rrsnn.network-joint-replay-validation.v1",allPassed:true,sourceHashes,
    completeStateRestores:restores,referenceCrashRecoveries:faultResults,rejections,
    pendingDelivery:{time:pendingTime,deliveries},
    physicalPulseCount:final.network.pulses.length,finalStateDigest:J.digest("rrsnn.network-final-state.v1",final),finalStats:stats,
    fixture:{weights,seed,scenario,model},golden:{checkpoint:pending,expectedFinal:final},
    evidenceScope:"actual delayed-network continuation and bounded reference journal/CAS/witness replay",
    referenceReplaysFromGenesis:true,filesystemDurabilityProven:false,productionOwnerExecuted:false,activationAllowed:false};
}
if(typeof module!=="undefined")module.exports={validateNetworkReplay};
if(typeof require==="function"&&require.main===module) {
  const fs=require("node:fs"),path=require("node:path");
  const names={engine:"event_runtime.cjs",continuation:"continuation_operator.cjs",network:"delayed_network.cjs",
    journal:"joint_replay.cjs",adapter:"network_joint_replay.cjs"};
  const sources=Object.fromEntries(Object.entries(names).map(([k,p])=>[k,fs.readFileSync(path.join(__dirname,p),"utf8")]));
  const out=validateNetworkReplay(require("./network_joint_replay.cjs"),require("./joint_replay.cjs"),
    require("./delayed_network.cjs"),require("./event_runtime.cjs"),require("./continuation_operator.cjs"),sources);
  console.log(JSON.stringify(out));
}
