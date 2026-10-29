"use strict";
/* Real marked-event continuations; journal crash points below are reference states. */
function validateReplay(J, E, C, sources) {
  const results=[], rejectCases=[];
  const assert=(ok,msg)=>{if(!ok)throw new Error(msg);};
  const clone=x=>JSON.parse(J.canonical(x));
  const eq=(a,b,msg)=>assert(J.canonical(a)===J.canonical(b),msg);
  const reject=(name,fn)=>{let error=null;try{fn();}catch(e){error=e.message;}assert(error,"accepted "+name);rejectCases.push({name,error});};
  const model={name:"fixed-test-policy",version:1,baseRate:4};
  const hooks={
    input:(observation,data)=>[2.5,4+data[0],0.5],
    continuation:(observation)=>0
  };
  const config={identity:"rrsnn.replay.fixture.v1",evidence:[1,2],
    channels:[{id:"up",from:0,to:1,rate:2.5,spike:false},{id:"pulse",from:1,to:0,rate:4,spike:true},
      {id:"down",from:1,to:0,rate:0.5,spike:false}],
    resetState:0,refractory:0.25,traceTau:1.25,pulseDebit:1,budgetCap:20,horizon:6,maxRecords:2000};
  const initial={stateIndex:0,budget:10,seed:971103,
    obligations:[{id:"a",deadline:1.5,renewDebit:1,renewLoss:0.1,emitDebit:1,emitValue:2,status:"live"},
      {id:"b",deadline:3,renewDebit:1,renewLoss:0.2,emitDebit:1,emitValue:3,status:"live"}],
    events:[{time:0.7,type:"input",data:[1]},{time:1.5,type:"shock",amount:2},
      {time:2.25,type:"refill",amount:4},{time:3,type:"control",rates:[3,6,0.5]},{time:4.2,type:"input",data:[0.5]}]};
  const sourceHashes=Object.fromEntries(Object.entries(sources).map(([k,v])=>[k,J.sha256(v)]));
  const options={Engine:E,Continuation:C,hooks,config,initial,sourceHashes,model};
  const A=J.bind(options), genesis=A.genesis;
  const whole=E.create(config,initial,C,hooks);whole.runUntil(6);
  const final=whole.snapshot(), finalStats=whole.statistics();
  assert(final.state.spikeCount>0,"fixture must contain actual pulses");
  assert(final.state.ledger.spentPulse===final.state.spikeCount,"all physical pulses are debited");
  for(const stop of [0,0.73,1.5,2.25,3.8,5.1]) {
    const saved=A.next(genesis,stop), encoded=J.canonical(saved);
    const restored=A.unpack(JSON.parse(encoded),saved.digest);restored.runUntil(6);
    eq(restored.snapshot(),final,"full state continuation differs at "+stop);
    eq(restored.statistics(),finalStats,"path statistics differ at "+stop);
    results.push({stop,pulsesBefore:saved.payload.snapshot.state.spikeCount,
      pulsesAfter:final.state.spikeCount-saved.payload.snapshot.state.spikeCount,
      completeStateExact:true,statisticsExact:true,checkpointDigest:saved.digest});
  }
  function stores() {
    const journal=new J.MemoryJournal(genesis), witness=new J.MemoryWitness(genesis.digest,J.anchor(genesis));
    const lease={owner:"owner.a",generation:journal.claim("owner.a",0)};
    return {journal,witness,lease,owner:J.open(A,journal,witness,lease,J.anchor(genesis))};
  }
  const faults=[];
  for(const fault of ["before_append","torn_tail","after_append","after_witness"]) {
    let s=stores(), first=s.owner.commit(J.anchor(genesis),{sequence:1,time:0.73});
    const minimum=J.anchor(first), request={sequence:2,time:2.25};
    reject("crash_"+fault,()=>s.owner.commit(minimum,request,fault));
    reject("poison_"+fault,()=>s.owner.commit(minimum,request));
    const journal=J.MemoryJournal.from(JSON.parse(J.canonical(s.journal.image())));
    const witness=J.MemoryWitness.from(JSON.parse(J.canonical(s.witness.image())));
    const lease={owner:"owner.b",generation:journal.claim("owner.b",s.lease.generation)};
    const owner=J.open(A,journal,witness,lease,minimum);
    const second=owner.commit(minimum,request);
    eq(second,A.next(first,2.25),"retry/reconcile changed checkpoint");
    const bytesBefore=J.canonical(journal.image());
    eq(owner.commit(minimum,request),second,"retry changed receipt");
    assert(bytesBefore===J.canonical(journal.image()),"exact retry wrote another frame");
    const last=owner.commit(J.anchor(second),{sequence:3,time:6});
    eq(last.payload.snapshot,final,"crash final state mismatch");
    faults.push({fault,frames:journal.image().frames.length,finalDigest:last.digest,recovered:true});
  }
  let s=stores(), first=s.owner.commit(J.anchor(genesis),{sequence:1,time:0.73});
  reject("stale_sequence",()=>s.owner.commit(J.anchor(first),{sequence:1,time:1}));
  reject("stale_head",()=>s.owner.commit(J.anchor(genesis),{sequence:2,time:1}));
  reject("time_regression",()=>s.owner.commit(J.anchor(first),{sequence:2,time:0.5}));
  reject("nonfinite_time",()=>s.owner.commit(J.anchor(first),{sequence:2,time:NaN}));
  const before=J.canonical(s.journal.image());
  reject("unknown_request_field",()=>s.owner.commit(J.anchor(first),{sequence:2,time:1,activate:true}));
  assert(before===J.canonical(s.journal.image()),"rejected request mutated journal");
  const lease2={owner:"owner.b",generation:s.journal.claim("owner.b",1)};
  reject("old_writer_fenced",()=>s.owner.commit(J.anchor(first),{sequence:2,time:1}));
  const newer=J.open(A,s.journal,s.witness,lease2,J.anchor(first));
  const second=newer.commit(J.anchor(first),{sequence:2,time:2.25});
  reject("witness_stale_CAS",()=>s.witness.cas(J.anchor(genesis),J.anchor(first)));
  reject("witness_rollback",()=>s.witness.cas(J.anchor(second),J.anchor(first)));
  const backup=s.journal.image();backup.frames.pop();
  reject("acknowledged_rollback",()=>J.open(A,J.MemoryJournal.from(backup),s.witness,lease2,J.anchor(second)));
  const corrupt=s.journal.image();corrupt.frames[0].checkpoint.payload.snapshot.state.clock.remaining+=0.01;
  reject("corrupt_complete_frame",()=>J.open(A,J.MemoryJournal.from(corrupt),s.witness,lease2,J.anchor(first)));
  const forged=s.journal.image(), frame=forged.frames[0];
  frame.checkpoint.payload.snapshot.state.clock.remaining+=0.01;
  frame.checkpoint.digest=J.digest(J.SCHEMA,frame.checkpoint.payload);
  const {digest:ignored,...body}=frame;frame.digest=J.digest("rrsnn.journal-frame.v1",body);
  reject("rehashed_false_physical_history",()=>J.open(A,J.MemoryJournal.from(forged),s.witness,lease2,J.anchor(first)));
  const reseal=(change)=>{const x=clone(first);change(x);x.digest=J.digest(J.SCHEMA,x.payload);return x;};
  reject("wrong_external_digest",()=>A.unpack(first,"0".repeat(64)));
  reject("unknown_envelope_field",()=>A.unpack({...first,activation:true}));
  reject("unknown_log_field",()=>A.unpack(reseal(x=>x.payload.snapshot.state.log[0].extra=1)));
  reject("changed_future_plan_resealed",()=>A.unpack(reseal(x=>x.payload.snapshot.state.queue.at(-1).data[0]+=1)));
  reject("unknown_rng_field",()=>A.unpack(reseal(x=>x.payload.snapshot.state.rng.extra=1)));
  reject("tampered_budget_resealed",()=>A.unpack(reseal(x=>x.payload.snapshot.state.budget+=1)));
  reject("nonfinite_physical_state",()=>{const x=clone(first);x.payload.snapshot.state.clock.remaining=Infinity;A.unpack(x);});
  reject("source_identity",()=>J.bind({...options,sourceHashes:{...sourceHashes,engine:"0".repeat(64)}}).unpack(first));
  reject("model_identity",()=>J.bind({...options,model:{...model,version:2}}).unpack(first));
  reject("config_identity",()=>J.bind({...options,config:{...config,identity:"wrong.profile"}}).unpack(first));
  reject("input_plan_identity",()=>J.bind({...options,initial:{...initial,seed:initial.seed+1}}).unpack(first));
  const atLimit=clone(first);atLimit.payload.sequence=1024;
  atLimit.digest=J.digest(J.SCHEMA,atLimit.payload);A.unpack(atLimit);
  reject("sequence_overflow",()=>A.next(atLimit,atLimit.payload.time));
  const edge=J.bind({...options,config:{...config,maxRecords:1},initial:{...initial,obligations:[],
    events:[{time:0,type:"control",rates:[0,0,0]}]}});
  assert(edge.next(edge.genesis,0.1).payload.snapshot.state.regimes.length===2,"valid maxRecords+1 regimes");
  const one=new J.MemoryJournal(genesis,1), capacityWitness=new J.MemoryWitness(genesis.digest,J.anchor(genesis));
  const own=J.open(A,one,capacityWitness,{owner:"capacity",generation:one.claim("capacity",0)},J.anchor(genesis));
  const onecp=own.commit(J.anchor(genesis),{sequence:1,time:0.73}), oneimage=J.canonical(one.image());
  reject("capacity_atomicity",()=>own.commit(J.anchor(onecp),{sequence:2,time:1}));
  assert(oneimage===J.canonical(one.image()),"capacity failure mutated state");
  assert(J.sha256("")==="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","SHA empty");
  assert(J.sha256("abc")==="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad","SHA abc");
  return {schema:"rrsnn.joint-replay-validation.v1",allPassed:true,sourceHashes,
    completeStateRestores:results,referenceCrashRecoveries:faults,rejections:rejectCases,
    actualFinalPulses:final.state.spikeCount,finalStateDigest:J.digest("rrsnn.final-state.v1",final),
    finalStats,fixture:{config,initial,model},golden:{checkpoint:first,expectedFinal:final},
    evidenceScope:"pure-JavaScript deterministic continuation and in-memory journal/CAS/witness state machine",
    filesystemDurabilityProven:false,networkRestoreProven:false,productionOwnerExecuted:false,activationAllowed:false};
}
if(typeof module!=="undefined") module.exports={validateReplay};
if(typeof require==="function" && require.main===module) {
  const fs=require("node:fs"),path=require("node:path");
  const load=name=>fs.readFileSync(path.join(__dirname,name),"utf8");
  const sources={engine:load("event_runtime.cjs"),continuation:load("continuation_operator.cjs"),adapter:load("joint_replay.cjs")};
  const result=validateReplay(require("./joint_replay.cjs"),require("./event_runtime.cjs"),require("./continuation_operator.cjs"),sources);
  console.log(JSON.stringify(result));
}
