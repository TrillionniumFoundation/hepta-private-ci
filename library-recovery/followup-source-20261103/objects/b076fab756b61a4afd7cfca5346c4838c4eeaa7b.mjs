import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm,symlink} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {collectProducerArtifacts,verifyProducerArtifacts} from '../tools/producer-artifacts.mjs';
async function fixture(t){
 const target=await mkdtemp(join(tmpdir(),'producer-artifact-'));t.after(()=>rm(target,{recursive:true,force:true}));const directory=join(target,'wasm32-unknown-unknown/release/build/widgets/a/out');await mkdir(directory,{recursive:true});
 const filenames=['rmeta','rlib'].map(ext=>join(directory,'libmakepad_widgets-a.'+ext));for(const file of filenames)await writeFile(file,'exact producer '+file.split('.').at(-1));
 const event={reason:'compiler-artifact',package_id:'git+https://example.invalid/sdk#revision',target:{name:'makepad_widgets',kind:['lib']},profile:{test:false},features:['default'],fresh:true,filenames};
 const options={target,sourceIdentity:'1'.repeat(64),compiler:'rustc pinned',required:{makepad_widgets:event.package_id}};const stream=JSON.stringify(event)+'\n'+JSON.stringify({reason:'build-finished',success:true})+'\nPackaged\n';return {target,filenames,event,options,stream};
}
test('fresh cache events select exact artifacts while unrelated retained variants are ignored',async t=>{
 const f=await fixture(t);const extra=join(f.target,'wasm32-unknown-unknown/old/libmakepad_widgets-b.rmeta');await mkdir(join(extra,'..'),{recursive:true});await writeFile(extra,'unrelated old variant');
 const receipt=await collectProducerArtifacts(f.stream,f.options);const result=await verifyProducerArtifacts(receipt,f.options);assert.equal(result.externs.makepad_widgets.rmeta,f.filenames[0]);assert.equal(result.dependencyDirectories.length,1);
});
test('two units in the actual producer invocation fail rather than choosing newest',async t=>{
 const f=await fixture(t);await assert.rejects(()=>collectProducerArtifacts(JSON.stringify(f.event)+'\n'+f.stream,f.options),/Ambiguous/);
});
test('failed, incomplete and malformed compiler streams fail closed',async t=>{
 const f=await fixture(t);for(const stream of [JSON.stringify(f.event),f.stream.replace('"success":true','"success":false'),'{invalid'])await assert.rejects(()=>collectProducerArtifacts(stream,f.options));
});
test('outside-target compiler paths and symlink files are rejected',async t=>{
 const f=await fixture(t);await assert.rejects(()=>collectProducerArtifacts(f.stream.replace(f.filenames[0],'/tmp/outside.rmeta'),f.options),/inside/);
 await rm(f.filenames[0]);await symlink(f.filenames[1],f.filenames[0]);await assert.rejects(()=>collectProducerArtifacts(f.stream,f.options),/symlink/);
});
test('source/compiler drift and forged selected package cannot prove an artifact',async t=>{
 const f=await fixture(t);const r=await collectProducerArtifacts(f.stream,f.options);
 for(const options of [{...f.options,sourceIdentity:'2'.repeat(64)},{...f.options,compiler:'other'},{...f.options,required:{makepad_widgets:'wrong package'}}])await assert.rejects(()=>verifyProducerArtifacts(r,options));
});
test('modified and missing retained artifacts are rejected',async t=>{
 const f=await fixture(t);const r=await collectProducerArtifacts(f.stream,f.options);await writeFile(f.filenames[0],'changed');await assert.rejects(()=>verifyProducerArtifacts(r,f.options));await rm(f.filenames[0]);await assert.rejects(()=>verifyProducerArtifacts(r,f.options));
});
test('forged relative traversal or selected-unit name fails closed',async t=>{
 const f=await fixture(t);const r=await collectProducerArtifacts(f.stream,f.options);const a=structuredClone(r);a.units[0].files[0].path='../other.rmeta';await assert.rejects(()=>verifyProducerArtifacts(a,f.options),/component/);const b=structuredClone(r);b.units[0].name='forged';await assert.rejects(()=>verifyProducerArtifacts(b,f.options));
});
test('artifact symlink ancestors are rejected before reading',async t=>{
 const f=await fixture(t);const original=join(f.target,'wasm32-unknown-unknown');const moved=join(f.target,'retained');const {rename}=await import('node:fs/promises');await rename(original,moved);await symlink(moved,original);await assert.rejects(()=>collectProducerArtifacts(f.stream,f.options),/symlink/);
});
