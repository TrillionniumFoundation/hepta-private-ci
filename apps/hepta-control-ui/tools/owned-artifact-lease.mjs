// Build/preview ownership only. The kernel releases the lock after the last
// inheriting compiler exits, including when its Node parent is killed.
import {execFileSync,spawn} from 'node:child_process';
import {closeSync,fstatSync,statSync,constants} from 'node:fs';
import {mkdtemp,rename,rm,lstat,open,readdir} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import {join,resolve,basename} from 'node:path';
import {fileURLToPath} from 'node:url';
const runner=fileURLToPath(new URL('./artifact-lock.py',import.meta.url));
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const names=['dist','dist-robrix-fixtures','dist-robrix-keyboard-trace'];
const hashPattern=/^[a-f0-9]{64}$/;
const exists=async path=>{try{return await lstat(path);}catch(e){if(e.code==='ENOENT')return null;throw e;}};

// All mutating child processes must use this adapter. Rust Command preserves
// the non-CLOEXEC descriptor when it starts Cargo/rustc descendants.
export function execOwned(file,args,options={}){
 if(!process.env.HEPTA_ARTIFACT_LOCK_ROOT)throw new Error('Missing kernel artifact lock');
 const mode=options.stdio??'pipe';
 if(!['pipe','inherit','ignore'].includes(mode))throw new Error('Unsupported owned child stdio');
 return execFileSync(file,args,{...options,stdio:[mode,mode,mode,3]});
}
export async function withArtifactLease(root,kind,work){
 root=resolve(root);
 if(process.env.HEPTA_ARTIFACT_LOCK_ROOT!==root){
  const child=spawn('python3',[runner,root,process.execPath,...process.argv.slice(1)],{stdio:'inherit'});
  const interrupt=()=>child.kill('SIGINT'),terminate=()=>child.kill('SIGTERM');
  process.on('SIGINT',interrupt);process.on('SIGTERM',terminate);
  const status=await new Promise((done,fail)=>{child.once('error',fail);child.once('exit',code=>done(code??1));});
  process.off('SIGINT',interrupt);process.off('SIGTERM',terminate);
  process.exit(status);
 }
 const fd=fstatSync(3),path=statSync(join(root,'.robrix-artifact.lock'));
 if(!fd.isFile()||fd.ino!==path.ino||fd.dev!==path.dev)throw new Error('Invalid kernel artifact lock descriptor');
 const lease={root};
 try{
  for(const name of names)await recoverArtifact(lease,name);
  if(kind==='preview')execOwned('python3',[runner,'--shared']);
  return await work(lease);
 }finally{closeSync(3);delete process.env.HEPTA_ARTIFACT_LOCK_ROOT;}
}
async function boundedFile(path,limit){
 const file=await open(path,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
 try{
  const info=await file.stat();
  if(!info.isFile()||info.size>limit)throw new Error('Nonregular or oversized artifact file');
  const bytes=Buffer.alloc(info.size+1);let offset=0;
  while(offset<bytes.length){const {bytesRead}=await file.read(bytes,offset,bytes.length-offset,null);if(!bytesRead)break;offset+=bytesRead;}
  if(offset!==info.size)throw new Error('Artifact changed while reading');
  return bytes.subarray(0,offset);
 }finally{await file.close();}
}
export async function loadArtifactSnapshot(path,expectedDigest){
 const info=await lstat(path);if(!info.isDirectory()||info.isSymbolicLink())throw new Error('Artifact root must be a regular directory');
 const bytes=await boundedFile(join(path,'build-manifest.json'),2*1024*1024);
 const manifestDigest=digest(bytes);
 if(expectedDigest&&manifestDigest!==expectedDigest)throw new Error('Retained manifest pin mismatch');
 const manifest=JSON.parse(bytes);
 if(manifest.schema!=='hepta.robrix-ui.build.v1'||manifest.browserRuntime!=='rust-makepad-wasm'||!hashPattern.test(manifest.sourceIdentity?.sha256))throw new Error('Invalid artifact manifest');
 const entries=Object.entries(manifest.files??{});
 if(entries.length===0||entries.length>128)throw new Error('Invalid artifact resource count');
 let total=0;const buffers=new Map([['build-manifest.json',bytes]]);
 for(const [name,pin] of entries){
  if(name==='build-manifest.json'||name.split('/').some(part=>!part||part==='.'||part==='..')||/[\\%\x00-\x1f]/.test(name)||!Number.isSafeInteger(pin.bytes)||pin.bytes<0||pin.bytes>64*1024*1024||!hashPattern.test(pin.sha256))throw new Error('Invalid artifact resource pin');
  total+=pin.bytes;if(total>128*1024*1024)throw new Error('Artifact aggregate limit exceeded');
  let parent=path;
  for(const part of name.split('/').slice(0,-1)){parent=join(parent,part);const st=await lstat(parent);if(!st.isDirectory()||st.isSymbolicLink())throw new Error('Symlink/non-directory artifact component');}
  const body=await boundedFile(join(path,name),pin.bytes);
  if(body.length!==pin.bytes||digest(body)!==pin.sha256)throw new Error('Artifact resource digest mismatch');
  buffers.set(name,body);
 }
 const actual=[];
 async function walk(dir,prefix=''){for(const item of await readdir(dir,{withFileTypes:true})){const rel=prefix+item.name;if(item.isDirectory())await walk(join(dir,item.name),rel+'/');else if(item.isFile())actual.push(rel);else throw new Error('Nonregular artifact entry');}}
 await walk(path);
 if(JSON.stringify(actual.sort())!==JSON.stringify([...buffers.keys()].sort()))throw new Error('Unlisted artifact resources');
 return {manifest,manifestDigest,buffers};
}
async function syncDirectory(path){const fd=await open(path,constants.O_RDONLY|constants.O_DIRECTORY|constants.O_NOFOLLOW);try{await fd.sync();}finally{await fd.close();}}
async function syncTree(path){for(const item of await readdir(path,{withFileTypes:true})){const child=join(path,item.name);if(item.isDirectory())await syncTree(child);else{const fd=await open(child,constants.O_RDONLY|constants.O_NOFOLLOW);try{await fd.sync();}finally{await fd.close();}}}await syncDirectory(path);}
function journalPath(root,name){if(!names.includes(name))throw new Error('Unexpected owned artifact name');return join(root,`.robrix-${name}.journal.json`);}
export async function recoverArtifact(lease,name){
 const path=journalPath(lease.root,name);if(!await exists(path))return;
 const record=JSON.parse(await boundedFile(path,4096));
 if(JSON.stringify(Object.keys(record).sort())!==JSON.stringify(['name','next','previous','previousDigest','stage','version'].sort())||record.version!==1||record.name!==name||!/^\.robrix-artifact-stage-[A-Za-z0-9]+$/.test(record.stage)||!/^\.robrix-artifact-previous-[a-f0-9-]{36}$/.test(record.previous)||!hashPattern.test(record.next)||(record.previousDigest!==null&&!hashPattern.test(record.previousDigest)))throw new Error('Unknown publication journal state');
 const dest=join(lease.root,name),stage=join(lease.root,record.stage),previous=join(lease.root,record.previous);
 const state=async p=>await exists(p)?(await loadArtifactSnapshot(p)).manifestDigest:null;
 let [d,s,p]=await Promise.all([state(dest),state(stage),state(previous)]);
 const old=record.previousDigest;
 if(d===old&&s===record.next&&p===null){
  if(old!==null){await rename(dest,previous);await syncDirectory(lease.root);}
  await rename(stage,dest);await syncDirectory(lease.root);
 }else if(d===null&&s===record.next&&p===old){
  await rename(stage,dest);await syncDirectory(lease.root);
 }else if(!(d===record.next&&s===null&&p===old))throw new Error('Publication state does not match retained manifest pins');
 // Revalidate before deleting the previous version; all readers use snapshots.
 await loadArtifactSnapshot(dest,record.next);
 if(old!==null)await loadArtifactSnapshot(previous,old);
 // Complete the transaction durably before garbage collection. A killed
 // recursive cleanup may leave an inert owned backup, never a broken journal.
 await rm(path);await syncDirectory(lease.root);
 if(old!==null)await rm(previous,{recursive:true});
}
export async function withStagedArtifact(lease,name,build){
 const journal=journalPath(lease.root,name);
 const stage=await mkdtemp(join(lease.root,'.robrix-artifact-stage-'));
 let journalCreated=false;
 try{
  await build(stage);
  const next=await loadArtifactSnapshot(stage);
  const destination=join(lease.root,name);
  const old=await exists(destination)?await loadArtifactSnapshot(destination):null;
  await syncTree(stage);
  const record={version:1,name,stage:basename(stage),previous:'.robrix-artifact-previous-'+randomUUID(),next:next.manifestDigest,previousDigest:old?.manifestDigest??null};
  const temp=journal+'.'+randomUUID()+'.tmp';
  try{
   const fd=await open(temp,'wx',0o600);try{await fd.writeFile(JSON.stringify(record));await fd.sync();}finally{await fd.close();}
   await rename(temp,journal);journalCreated=true;await syncDirectory(lease.root);
  }finally{await rm(temp,{force:true});}
  await recoverArtifact(lease,name);
 }finally{if(!journalCreated)await rm(stage,{recursive:true,force:true});}
}
