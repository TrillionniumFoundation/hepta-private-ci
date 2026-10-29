"use strict";
const fs=require("node:fs"),path=require("node:path"),cp=require("node:child_process");
const crypto=require("node:crypto");
const root=__dirname,out=process.env.RR_RESULTS_DIR||path.join(root,"audit-output");
fs.mkdirSync(out,{recursive:true});
const hash=(algorithm,bytes)=>crypto.createHash(algorithm).update(bytes).digest("hex");
const ordered=x=>Array.isArray(x)?x.map(ordered):x&&typeof x==="object"?
  Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])])):x;
const records=[];
for(const file of ["audit_network_optimization.cjs","audit_diagnostic_utility.cjs"]) {
  const result=cp.spawnSync(process.execPath,[path.join(root,file)],
    {encoding:"utf8",timeout:120000,maxBuffer:1024*1024});
  fs.writeFileSync(path.join(out,file+".stdout"),result.stdout||"");
  fs.writeFileSync(path.join(out,file+".stderr"),result.stderr||"");
  const record={file,status:result.status,signal:result.signal,
    success:result.status===0,error:result.error?String(result.error):null};
  try {
    record.result=JSON.parse(result.stdout);
    record.semanticSha256=hash("sha256",JSON.stringify(ordered(record.result)));
  } catch(error) {record.success=false;record.jsonError=String(error);}
  records.push(record);
}
const sources=fs.readdirSync(root).filter(x=>x.endsWith(".cjs")||
  x.endsWith("protocol.json")||x==="network_learning_results.json").sort().map(file=>{
    const bytes=fs.readFileSync(path.join(root,file));
    return {file,sha256:hash("sha256",bytes),
      gitBlobSha1:hash("sha1",Buffer.concat([Buffer.from("blob "+bytes.length+"\0"),bytes]))};
  });
const receipt={schema:"rr-snn-addendum-node-audit-1",
  sourceCommit:process.env.GITHUB_SHA||null,node:process.version,v8:process.versions.v8,
  platform:process.platform,arch:process.arch,allPassed:records.every(x=>x.success),
  baseVerifiedCommit:"13712a4a024a85f60dde6eb9a55877d34f186e03",
  baseVerifiedRun:40870313419,records,sources,
  scope:{newCandidateFitted:false,newHoldoutUsed:false,r4ArchitectureBenchmark:false,
    targetDotHost:false,realHeptaOwnerExecuted:false,activationAllowed:false}};
fs.writeFileSync(path.join(out,"receipt.json"),JSON.stringify(receipt,null,2)+"\n");
console.log(JSON.stringify(receipt));
if(!receipt.allPassed)process.exitCode=1;
