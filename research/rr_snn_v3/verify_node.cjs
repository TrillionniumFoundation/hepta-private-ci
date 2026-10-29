"use strict";
const fs=require("node:fs"),path=require("node:path"),cp=require("node:child_process");
const crypto=require("node:crypto");
const root=__dirname,out=process.env.RR_RESULTS_DIR||path.join(root,"verification-output");
fs.mkdirSync(out,{recursive:true});
const files=fs.readdirSync(root).filter(x=>/^validate(?:_.*)?\.cjs$/.test(x)).sort();
if(files.length===0)throw new Error("no validation entrypoints");
const records=[];
for(const file of files) {
  const result=cp.spawnSync(process.execPath,[path.join(root,file)],{
    encoding:"utf8",timeout:120000,maxBuffer:8*1024*1024});
  const record={file,status:result.status,signal:result.signal,
    error:result.error?String(result.error):null};
  fs.writeFileSync(path.join(out,file+".stdout"),result.stdout||"");
  fs.writeFileSync(path.join(out,file+".stderr"),result.stderr||"");
  if(result.status===0) {
    try{const parsed=JSON.parse(result.stdout);
      record.passed=parsed.passed??parsed.checks?.length??null;
    }catch{record.jsonOutput=false;}
  }
  records.push(record);console.log(JSON.stringify(record));
}
const sources=fs.readdirSync(root).filter(x=>x.endsWith(".cjs")).sort().map(file=>{
  const bytes=fs.readFileSync(path.join(root,file));
  const blob=Buffer.concat([Buffer.from("blob "+bytes.length+"\0"),bytes]);
  return {file,sha256:crypto.createHash("sha256").update(bytes).digest("hex"),
    gitBlobSha1:crypto.createHash("sha1").update(blob).digest("hex")};
});
const receipt={schema:"rr-snn-node-verification-1",sourceCommit:process.env.GITHUB_SHA||null,
  node:process.version,platform:process.platform,arch:process.arch,records,sources,
  scope:{functionalNodeExecution:true,targetDotHost:false,productionOwnerExecuted:false,
    actualFutureWindow:false,realHeptaCellBenchmark:false}};
fs.writeFileSync(path.join(out,"receipt.json"),JSON.stringify(receipt,null,2)+"\n");
console.log(JSON.stringify(receipt));
if(records.some(x=>x.status!==0))process.exitCode=1;
