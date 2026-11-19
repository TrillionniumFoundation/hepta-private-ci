"use strict";
/* Optional Linux/Node subprocess evidence; isolated temp files, no live owner. */
const fs=require("node:fs"),path=require("node:path"),os=require("node:os");
const {spawnSync}=require("node:child_process");
const J=require("./joint_replay.cjs"),E=require("./event_runtime.cjs"),C=require("./continuation_operator.cjs");
const assert=(ok,msg)=>{if(!ok)throw new Error(msg);};
const readJSON=p=>JSON.parse(fs.readFileSync(p,"utf8"));
const file=(d,n)=>path.join(d,n);
function syncDir(d) { const fd=fs.openSync(d,"r");try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);} }
function writeSynced(p,text,flags="w") {
  const fd=fs.openSync(p,flags,0o600),bytes=Buffer.from(text);
  try { for(let at=0;at<bytes.length;) {const n=fs.writeSync(fd,bytes,at,bytes.length-at);assert(n>0,"short write");at+=n;}fs.fsyncSync(fd); }
  finally {fs.closeSync(fd);}
}
function atomicJSON(p,x) {
  writeSynced(p+".new",J.canonical(x)+"\n");fs.renameSync(p+".new",p);syncDir(path.dirname(p));
}
function adapter(d) {
  const f=readJSON(file(d,"fixture.json"));
  const src={engine:"event_runtime.cjs",continuation:"continuation_operator.cjs",adapter:"joint_replay.cjs"};
  const sourceHashes=Object.fromEntries(Object.entries(src).map(([k,p])=>[k,J.sha256(fs.readFileSync(path.join(__dirname,p),"utf8"))]));
  return J.bind({Engine:E,Continuation:C,config:f.config,initial:f.initial,model:f.model,sourceHashes,
    hooks:{input:(obs,data)=>[2.5,4+data[0],0.5],continuation:obs=>0}});
}
function meta(image) {const {frames,tail,...rest}=image;return rest;}
function loadDisk(d) {
  const raw=fs.readFileSync(file(d,"journal.ndjson"),"utf8"),at=raw.lastIndexOf("\n")+1;
  const frames=at?raw.slice(0,at-1).split("\n").map(x=>JSON.parse(x)):[];
  const tail=at<raw.length?{incomplete:true,prefix:raw.slice(at)}:null;
  return {journal:J.MemoryJournal.from({...readJSON(file(d,"meta.json")),frames,tail}),
    witness:J.MemoryWitness.from(readJSON(file(d,"witness.json"))),validBytes:Buffer.byteLength(raw.slice(0,at)),tail};
}
function worker(d,commandPath,fault) {
  assert(["none","before_append","torn_tail","after_append","after_witness"].includes(fault),"fault");
  const lock=file(d,"owner.lock");let owned=false;
  try {
    writeSynced(lock,J.canonical({pid:process.pid})+"\n","wx");owned=true;syncDir(d);
    const A=adapter(d),s=loadDisk(d),command=readJSON(commandPath);
    const lease={owner:"process."+process.pid,generation:s.journal.claim("process."+process.pid,s.journal.data.fence.generation)};
    atomicJSON(file(d,"meta.json"),meta(s.journal.image()));
    const owner=J.open(A,s.journal,s.witness,lease,readJSON(file(d,"minimum.json")));
    if(s.tail) {
      const fd=fs.openSync(file(d,"journal.ndjson"),"r+");try{fs.ftruncateSync(fd,s.validBytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    }
    atomicJSON(file(d,"witness.json"),s.witness.image());
    const oldLength=s.journal.data.frames.length,cp=owner.commit(command.expected,command.request);
    const crash=()=>process.kill(process.pid,"SIGKILL");
    if(fault==="before_append")crash();
    if(s.journal.data.frames.length>oldLength) {
      const line=J.canonical(s.journal.data.frames.at(-1))+"\n";
      if(fault==="torn_tail"){writeSynced(file(d,"journal.ndjson"),line.slice(0,127),"a");crash();}
      writeSynced(file(d,"journal.ndjson"),line,"a");
    }
    if(fault==="after_append")crash();
    atomicJSON(file(d,"witness.json"),s.witness.image());
    if(fault==="after_witness")crash();
    return {checkpoint:cp,appended:s.journal.data.frames.length-oldLength,
      journalDigest:J.sha256(fs.readFileSync(file(d,"journal.ndjson"),"utf8"))};
  } finally {if(owned){fs.unlinkSync(lock);syncDir(d);}}
}
function main() {
  assert(process.platform==="linux","this fsync/SIGKILL fixture requires Linux");
  const names={engine:"event_runtime.cjs",continuation:"continuation_operator.cjs",adapter:"joint_replay.cjs"};
  const sources=Object.fromEntries(Object.entries(names).map(([k,p])=>[k,fs.readFileSync(path.join(__dirname,p),"utf8")]));
  const base=require("./validate_replay.cjs").validateReplay(J,E,C,sources);
  const root=fs.mkdtempSync(path.join(os.tmpdir(),"rrsnn-fs-replay-"));
  const results=[],rejections=[];
  const fixture={...base.fixture,model:{...base.fixture.model,fsHarnessSourceSha256:J.sha256(fs.readFileSync(__filename,"utf8"))}};
  function call(d,command,fault="none",failure=false) {
    atomicJSON(file(d,"command.json"),command);
    const p=spawnSync(process.execPath,[__filename,"--worker",d,file(d,"command.json"),fault],
      {encoding:"utf8",timeout:15000,maxBuffer:2*1024*1024});
    assert(!p.error,"child launch/timeout: "+String(p.error));
    // Only the supervisor that observed this exact child exit removes its dead lock.
    const lock=file(d,"owner.lock");
    if(fs.existsSync(lock)&&readJSON(lock).pid===p.pid){fs.unlinkSync(lock);syncDir(d);}
    if(fault!=="none"){assert(p.signal==="SIGKILL","fault did not kill child: "+p.stderr);return p;}
    if(failure){assert(p.status!==0&&p.stderr.includes(failure),"wrong negative failure: "+p.stderr);return p.stderr.trim().split("\n")[0];}
    assert(p.status===0,"child failed: "+p.stderr);
    const receipt=JSON.parse(p.stdout);
    atomicJSON(file(d,"minimum.json"),J.anchor(receipt.checkpoint));
    return receipt;
  }
  let lastDir;
  try {
    for(const fault of ["before_append","torn_tail","after_append","after_witness"]) {
      const d=file(root,fault);fs.mkdirSync(d,{mode:0o700});syncDir(root);lastDir=d;
      atomicJSON(file(d,"fixture.json"),fixture);
      const A=adapter(d),j=new J.MemoryJournal(A.genesis),w=new J.MemoryWitness(A.genesis.digest,J.anchor(A.genesis));
      atomicJSON(file(d,"meta.json"),meta(j.image()));atomicJSON(file(d,"witness.json"),w.image());
      atomicJSON(file(d,"minimum.json"),J.anchor(A.genesis));writeSynced(file(d,"journal.ndjson"),"");syncDir(d);
      const first=call(d,{expected:J.anchor(A.genesis),request:{sequence:1,time:0.73}});
      const command={expected:J.anchor(first.checkpoint),request:{sequence:2,time:2.25}};
      call(d,command,fault);
      const second=call(d,command),before=fs.readFileSync(file(d,"journal.ndjson"),"utf8");
      const retry=call(d,command);
      assert(retry.appended===0&&before===fs.readFileSync(file(d,"journal.ndjson"),"utf8"),"retry appended duplicate");
      assert(J.canonical(second.checkpoint)===J.canonical(A.next(first.checkpoint,2.25)),"recovery differs");
      const last=call(d,{expected:J.anchor(second.checkpoint),request:{sequence:3,time:6}});
      assert(J.canonical(last.checkpoint.payload.snapshot)===J.canonical(base.golden.expectedFinal),"final physical state differs");
      results.push({fault,killedSignal:"SIGKILL",restartStateExact:true,finalDigest:last.checkpoint.digest,
        finalPulses:last.checkpoint.payload.snapshot.state.spikeCount,retryAppended:retry.appended});
    }
    const d=lastDir,A=adapter(d),cmd={expected:J.anchor(A.genesis),request:{sequence:4,time:6}};
    const oldBytes=fs.readFileSync(file(d,"journal.ndjson"),"utf8");
    rejections.push({name:"stale_expected_head",error:call(d,cmd,"none","stale head/sequence")});
    assert(oldBytes===fs.readFileSync(file(d,"journal.ndjson"),"utf8"),"stale request changed journal");
    writeSynced(file(d,"owner.lock"),J.canonical({pid:-1})+"\n","wx");
    rejections.push({name:"exclusive_owner_lock",error:call(d,cmd,"none","EEXIST")});fs.unlinkSync(file(d,"owner.lock"));syncDir(d);
    const lines=oldBytes.trimEnd().split("\n"),bad=JSON.parse(lines[0]);bad.checkpoint.payload.snapshot.state.clock.remaining+=0.01;
    writeSynced(file(d,"journal.ndjson"),[J.canonical(bad),...lines.slice(1)].join("\n")+"\n");
    rejections.push({name:"corrupt_complete_record",error:call(d,cmd,"none","journal frame checksum")});
    writeSynced(file(d,"journal.ndjson"),lines.slice(0,-1).join("\n")+"\n");
    rejections.push({name:"acknowledged_file_rollback",error:call(d,cmd,"none","acknowledged rollback")});
    const out={schema:"rrsnn.fs-replay-validation.v1",allPassed:true,node:process.version,v8:process.versions.v8,
      platform:process.platform,arch:process.arch,sourceHashes:base.sourceHashes,harnessSourceSha256:fixture.model.fsHarnessSourceSha256,
      filesystemType:typeof fs.statfsSync==="function"?Number(fs.statfsSync(root).type):null,
      crashRecoveries:results,rejections,evidenceScope:"actual temporary files, fsync calls, SIGKILL and separate Node process restart",
      singleSupervisorProcessesOnly:true,powerLossDurabilityProven:false,productionOwnerExecuted:false,
      networkRestoreProven:false,targetMachinePerformanceProven:false,activationAllowed:false};
    console.log(JSON.stringify(out));
    return out;
  } finally {fs.rmSync(root,{recursive:true,force:true});}
}
if(require.main===module) {
  try {if(process.argv[2]==="--worker")console.log(JSON.stringify(worker(process.argv[3],process.argv[4],process.argv[5])));else main();}
  catch(error){console.error(error.stack);process.exitCode=1;}
}
module.exports={main};
