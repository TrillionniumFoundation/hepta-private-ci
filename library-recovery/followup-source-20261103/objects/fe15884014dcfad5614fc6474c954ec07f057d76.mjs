// Build/probe tooling only. This record is integrity evidence, not signing authority.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {lstat,open} from 'node:fs/promises';
import {isAbsolute,join,relative,resolve,sep} from 'node:path';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const MAX_STREAM=32*1024*1024,MAX_FILE=64*1024*1024,MAX_TOTAL=512*1024*1024;
const extension=/\.(?:rmeta|rlib|so|dylib|dll)$/;
function contained(root,path){
 const value=relative(root,resolve(path));
 assert.ok(value&&!isAbsolute(value)&&value!=='..'&&!value.startsWith('..'+sep),'Artifact must be inside the owned target');
 return value.split(sep).join('/');
}
async function bytesAt(target,name){
 const root=await lstat(target);assert.ok(root.isDirectory()&&!root.isSymbolicLink(),'Owned target must be a real directory');
 assert.ok(typeof name==='string'&&name.length<4096&&!isAbsolute(name)&&extension.test(name),'Artifact path must be relative metadata/library');
 const parts=name.split('/');assert.ok(parts.every(p=>p&&p!=='.'&&p!=='..'),'Invalid artifact path component');
 let path=target;
 for(const part of parts){path=join(path,part);const stat=await lstat(path);assert.equal(stat.isSymbolicLink(),false,'Artifact path cannot contain a symlink');}
 const file=await open(path,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
 try{
  const stat=await file.stat();assert.ok(stat.isFile()&&stat.size>0&&stat.size<=MAX_FILE,'Artifact must be a bounded regular file');
  const buffer=Buffer.alloc(stat.size+1);let size=0;
  while(size<buffer.length){const r=await file.read(buffer,size,buffer.length-size,null);if(!r.bytesRead)break;size+=r.bytesRead;}
  assert.equal(size,stat.size,'Artifact changed size during bounded read');return buffer.subarray(0,size);
 }finally{await file.close();}
}
export async function collectProducerArtifacts(stream,{target,sourceIdentity,compiler,required}){
 assert.ok(Buffer.byteLength(stream)<=MAX_STREAM,'Compiler event stream exceeds bound');
 assert.match(sourceIdentity,/^[a-f0-9]{64}$/);assert.ok(typeof compiler==='string'&&compiler.length<200);
 target=resolve(target);const units=[];let finished=0,total=0;
 for(const line of stream.split('\n')){
  if(!line.trim().startsWith('{'))continue;const event=JSON.parse(line);
  if(event.reason==='build-finished'){assert.equal(event.success,true,'Compiler did not finish successfully');finished++;continue;}
  if(event.reason!=='compiler-artifact')continue;
  assert.ok(units.length<2048&&typeof event.package_id==='string'&&event.package_id.length<4096,'Invalid compiler unit');
  assert.ok(event.target&&typeof event.target.name==='string'&&Array.isArray(event.target.kind)&&Array.isArray(event.filenames),'Invalid compiler artifact event');
  assert.ok(event.filenames.length<=16&&Array.isArray(event.features)&&event.features.length<=64,'Unbounded compiler unit');
  const files=[];
  for(const path of event.filenames){
   if(!extension.test(path))continue;const name=contained(target,path),bytes=await bytesAt(target,name);total+=bytes.length;assert.ok(total<=MAX_TOTAL,'Compiler artifacts exceed total bound');
   files.push({path:name,bytes:bytes.length,sha256:sha(bytes)});
  }
  if(files.length)units.push({name:event.target.name,kind:event.target.kind,packageIdSha256:sha(event.package_id),features:event.features,profile:event.profile,files});
 }
 assert.equal(finished,1,'Require one completed producer invocation');
 const selections={};
 for(const [name,packageId] of Object.entries(required)){
  const matching=units.filter(u=>u.name===name&&u.packageIdSha256===sha(packageId)&&u.files.some(f=>f.path.startsWith('wasm32-unknown-unknown/')&&f.path.endsWith('.rmeta')));
  assert.equal(matching.length,1,'Ambiguous or missing producer unit: '+name);
  const unit=matching[0];assert.ok(unit.kind.includes('lib')||unit.kind.includes('rlib'),'Probe dependency must be a library');
  for(const suffix of ['.rmeta','.rlib'])assert.equal(unit.files.filter(f=>f.path.endsWith(suffix)).length,1,'Missing or ambiguous '+name+suffix);
  selections[name]=units.indexOf(unit);
 }
 return {schema:'hepta.compiler-artifacts.v1',sourceIdentity,compiler,streamSha256:sha(stream),units,selections};
}
export async function verifyProducerArtifacts(receipt,{target,sourceIdentity,compiler,required}){
 assert.equal(receipt.schema,'hepta.compiler-artifacts.v1');assert.equal(receipt.sourceIdentity,sourceIdentity,'Stale producer source');assert.equal(receipt.compiler,compiler,'Different producer compiler');
 assert.match(receipt.streamSha256,/^[a-f0-9]{64}$/);assert.ok(Array.isArray(receipt.units)&&receipt.units.length<=2048);
 let total=0;const directories=new Set(),externs={};
 for(const unit of receipt.units){
  assert.ok(Array.isArray(unit.files)&&unit.files.length<=16);
  for(const file of unit.files){const bytes=await bytesAt(resolve(target),file.path);total+=bytes.length;assert.ok(total<=MAX_TOTAL);assert.equal(bytes.length,file.bytes);assert.equal(sha(bytes),file.sha256,'Artifact bytes changed');directories.add(resolve(target,file.path,'..'));}
 }
 assert.deepEqual(Object.keys(receipt.selections).sort(),Object.keys(required).sort(),'Probe selection contract changed');
 for(const [name,packageId] of Object.entries(required)){
  const index=receipt.selections[name];assert.ok(Number.isSafeInteger(index)&&index>=0&&index<receipt.units.length);
  const unit=receipt.units[index];assert.ok(Array.isArray(unit.kind)&&(unit.kind.includes('lib')||unit.kind.includes('rlib')),'Selected producer unit must be a library');assert.equal(unit.name,name);assert.equal(unit.packageIdSha256,sha(packageId),'Wrong package selected');
  const matching=receipt.units.filter(u=>u.name===name&&u.packageIdSha256===sha(packageId)&&u.files.some(f=>f.path.startsWith('wasm32-unknown-unknown/')&&f.path.endsWith('.rmeta')));
  assert.equal(matching.length,1,'Ambiguous producer selection');assert.equal(matching[0],unit);
  externs[name]={};for(const suffix of ['rmeta','rlib']){const files=unit.files.filter(f=>f.path.startsWith('wasm32-unknown-unknown/')&&f.path.endsWith('.'+suffix));assert.equal(files.length,1);externs[name][suffix]=resolve(target,files[0].path);}
 }
 return {externs,dependencyDirectories:[...directories].sort()};
}
