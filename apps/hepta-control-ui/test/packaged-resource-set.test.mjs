// Integration check against an actual owned build, not a source-only receipt.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {robrixSourceIdentity} from '../tools/robrix-source-identity.mjs';
const root=fileURLToPath(new URL('..',import.meta.url));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
async function below(directory,prefix=''){
 const result=[];
 for(const entry of await readdir(directory,{withFileTypes:true})){
  const path=prefix+entry.name;
  if(entry.isDirectory())result.push(...await below(join(directory,entry.name),path+'/'));
  else {assert.ok(entry.isFile(),'Only regular packaged resources');result.push(path);}
 }
 return result;
}
test('current owned build contains exactly its manifest and no archived resource aliases',async()=>{
 const dist=join(root,'dist');
 const manifest=JSON.parse(await readFile(join(dist,'build-manifest.json'),'utf8'));
 const files=await below(dist);
 assert.deepEqual(files.sort(),[...Object.keys(manifest.files),'build-manifest.json'].sort());
 for(const [path,expected] of Object.entries(manifest.files)){
  const bytes=await readFile(join(dist,path));
  assert.equal(bytes.length,expected.bytes,path);assert.equal(sha(bytes),expected.sha256,path);
 }
 const catalog=JSON.parse(await readFile(join(root,'rust/robrix-ui/patches/web-asset-paths.json'),'utf8'));
 const wasm=Object.keys(manifest.files).filter(path=>/^hepta-robrix\.[a-f0-9]+\.wasm$/.test(path));assert.equal(wasm.length,1);
 assert.deepEqual(Object.keys(manifest.files).sort(),[...catalog.files,...wasm].sort(),'unexpected packaged resource');
 const art=JSON.parse(await readFile(join(root,'rust/robrix-ui/resources/ASSETS.json'),'utf8'));
 for(const asset of art.archivedAssets??[]){
  assert.ok(!files.some(path=>path.endsWith('/'+asset.path)||path===asset.path),'archived art survived generated-package reuse');
 }
 assert.equal(manifest.sourceIdentity.sha256,(await robrixSourceIdentity(root)).sha256,'rebuild current source first');
});
