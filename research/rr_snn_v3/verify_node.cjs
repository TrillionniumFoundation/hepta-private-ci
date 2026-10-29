"use strict";
const fs=require("node:fs"),path=require("node:path"),cp=require("node:child_process");
const crypto=require("node:crypto");
const root=__dirname,out=process.env.RR_RESULTS_DIR||path.join(root,"verification-output");
fs.mkdirSync(out,{recursive:true});
const sha256=bytes=>crypto.createHash("sha256").update(bytes).digest("hex");
const ordered=x=>Array.isArray(x)?x.map(ordered):x&&typeof x==="object"?
  Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])])):x;
const files=fs.readdirSync(root).filter(x=>/^validate(?:_.*)?\.cjs$/.test(x)).sort();
if(files.length===0)throw new Error("no validation entrypoints");
if(fs.existsSync(path.join(root,"learn_network.cjs")))files.push("learn_network.cjs");
const records=[];
for(const file of files) {
  if(file==="learn_network.cjs"&&records.some(r=>!r.success)) {
    records.push({file,success:false,skipped:"functional gate failed"});continue;
  }
  const result=cp.spawnSync(process.execPath,[path.join(root,file)],{
    encoding:"utf8",timeout:120000,maxBuffer:8*1024*1024});
  const record={file,status:result.status,signal:result.signal,
    error:result.error?String(result.error):null,success:result.status===0};
  fs.writeFileSync(path.join(out,file+".stdout"),result.stdout||"");
  fs.writeFileSync(path.join(out,file+".stderr"),result.stderr||"");
  if(result.status===0) {
    try {
      const parsed=JSON.parse(result.stdout);
      record.passed=parsed.passed??parsed.checks_passed??parsed.checks?.length??null;
      record.stdoutSha256=sha256(result.stdout);
      record.semanticSha256=sha256(JSON.stringify(ordered(parsed)));
      if(parsed.allPassed===false||parsed.checks?.some(x=>x.passed===false))
        record.success=false;
      if(file==="validate_replay.cjs")record.summary={
        allPassed:parsed.allPassed,restores:parsed.completeStateRestores.length,
        referenceCrashes:parsed.referenceCrashRecoveries.length,
        rejected:parsed.rejections.length,physicalPulses:parsed.actualFinalPulses,
        sourceHashes:parsed.sourceHashes};
      if(file==="validate_replay_fs.cjs")record.result=parsed;
      if(file==="learn_network.cjs")record.summary={
        teacherWeights:parsed.teacherWeights,learnedWeights:parsed.learnedWeights,
        scores:parsed.scores,pairedDifference:parsed.pairedDifference,
        allGradientsFinite:parsed.optimizer.every(x=>x.allFinite),
        trainEpisodes:parsed.trainEpisodes.length,heldoutEpisodes:parsed.heldoutEpisodes.length,
        scope:parsed.scope};
    } catch(error) {record.jsonError=String(error);record.success=false;}
  } else record.stderr=(result.stderr||"").slice(0,12000);
  records.push(record);console.log(JSON.stringify(record));
}
const sources=fs.readdirSync(root).filter(x=>x.endsWith(".cjs")||x.endsWith("protocol.json"))
  .sort().map(file=>{
    const bytes=fs.readFileSync(path.join(root,file));
    const blob=Buffer.concat([Buffer.from("blob "+bytes.length+"\0"),bytes]);
    return {file,sha256:sha256(bytes),
      gitBlobSha1:crypto.createHash("sha1").update(blob).digest("hex")};
  });
const receipt={schema:"rr-snn-node-verification-2",sourceCommit:process.env.GITHUB_SHA||null,
  networkProtocolFreeze:"16ecf52b7faaa43e9ab0612cc22b5dd35345f063",
  node:process.version,v8:process.versions.v8,platform:process.platform,arch:process.arch,
  allPassed:records.every(x=>x.success),records,sources,
  scope:{functionalNodeExecution:true,targetDotHost:false,productionOwnerExecuted:false,
    actualFutureWindow:false,realHeptaCellBenchmark:false}};
fs.writeFileSync(path.join(out,"receipt.json"),JSON.stringify(receipt,null,2)+"\n");
console.log(JSON.stringify(receipt));
if(!receipt.allPassed)process.exitCode=1;
