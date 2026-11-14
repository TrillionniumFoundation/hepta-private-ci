import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateConsumer,readConsumerSnapshot,assertOptionalOutcome} from '../tools/font-consumer-diagnostic.mjs';
const path='/makepad_widgets/resources/IBMPlexSans-Text.ttf',abs='/source/font.ttf',hash='a'.repeat(64);
function sample(){
 const snapshot={version:2,nonce:17,sealed:true,overflow:false,hashedBytes:30,events:[
  {seq:1,stage:'http-response',request:'4611686018427387906',publicRequest:'18446744073709551615'},
  {seq:2,stage:'adopt',request:'18446744073709551615',pathHex:Buffer.from(abs).toString('hex'),bytes:10,sha256:hash},
  {seq:3,stage:'define',font:'18446744073709551614',pathHex:Buffer.from(abs).toString('hex'),bytes:10,sha256:hash},
  {seq:4,stage:'parse-start',font:'18446744073709551614'},
  {seq:5,stage:'parse',font:'18446744073709551614',bytes:10,sha256:hash},
  {seq:6,stage:'draw',font:'18446744073709551614',glyph:38,kind:1},
 ]};
 const delivery={records:[{path,request:'4611686018427387906',bytes:10,sha256:hash}]};
 return bindManifest({snapshot,delivery,options:{nonce:17,requiredUsePaths:[path]}});
}
function bindManifest(x){
 const resources=Object.fromEntries(x.delivery.records.map(record=>{
  const mapping=x.snapshot.events.find(event=>event.stage==='http-response'&&event.request===record.request);
  const event=x.snapshot.events.find(event=>event.stage==='adopt'&&event.request===mapping.publicRequest);
  return [record.path,{absolutePath:Buffer.from(event.pathHex,'hex').toString(),dependencyPath:record.path.slice(1),bytes:record.bytes,sha256:record.sha256}];
 }));
 x.options.manifest={threads:false,fixtures:false,fontConsumerResources:resources,files:Object.fromEntries(x.delivery.records.map(r=>[r.path.slice(1),{bytes:r.bytes,sha256:r.sha256}]))};
 return x;
}
const validate=x=>validateConsumer(x.snapshot,x.delivery,x.options);
test('exact request digest parser and natural-instance chain passes scoped diagnostic',()=>{
 const result=validate(sample());assert.equal(result.passed,true);assert.equal(result.observations[0].naturallyEmitted,true);
 assert.equal(result.observations[0].request,'4611686018427387906');
 assert.equal(result.observations[0].publicRequest,'18446744073709551615');
});
test('adoption alone is not parsing or required use',()=>{
 const x=sample();x.snapshot.events=x.snapshot.events.slice(0,2);assert.equal(validate(x).passed,false);
});
test('parsed but never naturally emitted fails required use',()=>{
 const x=sample();x.snapshot.events.pop();assert.equal(validate(x).passed,false);
});
test('no packaged-font blanket use requirement',()=>{
 const x=sample();x.delivery.records.push({path:'/optional.ttf',request:'11',bytes:3,sha256:hash});
 x.snapshot.events.push(
  {seq:7,stage:'http-response',request:'11',publicRequest:'5'},
  {seq:8,stage:'adopt',request:'5',pathHex:Buffer.from('/source/optional.ttf').toString('hex'),bytes:3,sha256:hash},
 );
 bindManifest(x);const r=validate(x);assert.equal(r.passed,true);assert.equal(r.observations[1].parsed,false);assert.equal(r.observations[1].naturallyEmitted,false);
});
test('an unfinished actual parser attempt fails even outside required-use subset',()=>{
 const x=sample(),pathHex=Buffer.from('/source/optional.ttf').toString('hex');
 x.delivery.records.push({path:'/optional.ttf',request:'11',bytes:3,sha256:hash});
 x.snapshot.events.push(
  {seq:7,stage:'http-response',request:'11',publicRequest:'5'},
  {seq:8,stage:'adopt',request:'5',pathHex,bytes:3,sha256:hash},
  {seq:9,stage:'define',font:'8',pathHex,bytes:3,sha256:hash},
  {seq:10,stage:'parse-start',font:'8'},
 );
 bindManifest(x);assert.equal(validate(x).passed,false);
});
for(const [name,change]of [
 ['stale nonce',x=>x.snapshot.nonce++],['overflow',x=>x.snapshot.overflow=true],['unsealed',x=>x.snapshot.sealed=false],
 ['wrong adoption hash',x=>x.snapshot.events[1].sha256='b'.repeat(64)],['wrong parser hash',x=>x.snapshot.events[4].sha256='b'.repeat(64)],
 ['wrong font',x=>x.snapshot.events[5].font='19'],['missing glyph',x=>x.snapshot.events[5].glyph=0],
 ['wrong resource',x=>x.snapshot.events[2].pathHex=Buffer.from('/other.ttf').toString('hex')],
 ['reused sequence',x=>x.snapshot.events[5].seq=3],['duplicate adoption',x=>x.snapshot.events.push({...x.snapshot.events[1],seq:7})],
 ['duplicate parser',x=>x.snapshot.events.push({...x.snapshot.events[4],seq:7})],['duplicate draw',x=>x.snapshot.events.push({...x.snapshot.events[5],seq:7})],
 ['wrong request',x=>x.snapshot.events[1].request='42'],['lost adoption',x=>x.snapshot.events.splice(1,1)],
 ['parse missing',x=>{x.snapshot.events.splice(4,1);x.snapshot.events[4].seq=5;}],
 ['early draw',x=>{[x.snapshot.events[4],x.snapshot.events[5]]=[x.snapshot.events[5],x.snapshot.events[4]];x.snapshot.events[4].seq=5;x.snapshot.events[5].seq=6;}],
 ['unknown event',x=>x.snapshot.events[5].stage='forged'],['no required scope',x=>x.options.requiredUsePaths=[]],
 ['duplicate delivery request',x=>x.delivery.records.push({...x.delivery.records[0]})],
 ['old unbound schema',x=>x.snapshot.version=1],
 ['wrong transport ID',x=>x.snapshot.events[0].request='4611686018427387907'],
 ['wrong public ID',x=>x.snapshot.events[0].publicRequest='2'],
 ['rounded transport ID',x=>x.snapshot.events[0].request=Number(x.snapshot.events[0].request)],
 ['reused transport ID',x=>x.snapshot.events.push({...x.snapshot.events[0],seq:7,publicRequest:'7'})],
 ['reused public ID',x=>x.snapshot.events.push({...x.snapshot.events[0],seq:7,request:'7'})],
 ['late mapping',x=>{[x.snapshot.events[0],x.snapshot.events[1]]=[x.snapshot.events[1],x.snapshot.events[0]];x.snapshot.events[0].seq=1;x.snapshot.events[1].seq=2;}],
 ['missing mapping',x=>{x.snapshot.events.shift();x.snapshot.events.forEach((event,index)=>event.seq=index+1);}],
])test(name+' is rejected',()=>{const x=sample();change(x);assert.equal(validate(x).passed,false);});
test('unrelated observed HTTP responses do not claim font adoption',()=>{
 const x=sample();x.snapshot.events.push({seq:7,stage:'http-response',request:'17',publicRequest:'19'});
 const result=validate(x);assert.equal(result.passed,true);assert.equal(result.observations.length,1);
});
test('snapshot reads only private remote object and fails on Rust/remote error',async()=>{
 let call;const session={async send(method,args){call={method,args};return {result:{value:sample().snapshot}};}};
 assert.equal((await readConsumerSnapshot(session,'private-handle',17)).nonce,17);
 assert.equal(call.method,'Runtime.callFunctionOn');assert.equal(call.args.objectId,'private-handle');
 assert.ok(!call.args.functionDeclaration.includes('console'));
 await assert.rejects(readConsumerSnapshot({async send(){return{exceptionDetails:{text:'trapped'}};}},'private',17));
});

test('coordinated adoption/definition absolute path change cannot rename expected resource',()=>{
 const x=sample();for(const index of [1,2])x.snapshot.events[index].pathHex=Buffer.from('/other.ttf').toString('hex');
 assert.equal(validate(x).passed,false);
});
test('changing both delivered and consumer digest cannot bypass immutable manifest',()=>{
 const x=sample();x.delivery.records[0].sha256='b'.repeat(64);
 for(const index of [1,2,4])x.snapshot.events[index].sha256='b'.repeat(64);
 assert.equal(validate(x).passed,false);
});
test('optional failure propagates only when no original product failure exists',()=>{
 assert.throws(()=>assertOptionalOutcome(false));
 assert.doesNotThrow(()=>assertOptionalOutcome(false,{priorFailure:true}));
 assert.doesNotThrow(()=>assertOptionalOutcome(true));
});
async function readUsingMemory({ptr=16,len,growAt,shared=false}={}){
 const bytes=Buffer.from(JSON.stringify(sample().snapshot));
 const memory=new WebAssembly.Memory({initial:1,maximum:2,...(shared?{shared:true}:{})});
 new Uint8Array(memory.buffer,16,bytes.length).set(bytes);
 const exports={
  hepta_font_consumer_seal(){if(growAt==='seal')memory.grow(1);return 1;},
  hepta_font_consumer_snapshot_ptr(){if(growAt==='ptr')memory.grow(1);return ptr;},
  hepta_font_consumer_snapshot_len(){if(growAt==='len')memory.grow(1);return len===undefined?bytes.length:len;},
 };
 const session={async send(method,args){
  try{return {result:{value:Function('return ('+args.functionDeclaration+')')().call({exports,memory},17)}};}
  catch(error){return {exceptionDetails:{text:String(error)}};}
 }};
 return readConsumerSnapshot(session,'private-memory',17);
}
for(const growAt of ['seal','ptr','len'])test('snapshot reacquires buffer after memory growth in '+growAt,async()=>{
 assert.equal((await readUsingMemory({growAt})).nonce,17);
});
for(const [name,options]of [
 ['NaN pointer',{ptr:NaN}],['fractional pointer',{ptr:1.5}],['over-width pointer',{ptr:2**32+16}],
 ['out-of-bounds pointer',{ptr:65535}],['zero length',{len:0}],['fractional length',{len:1.5}],
 ['oversized length',{len:256*1024+1}],['shared memory',{shared:true}],
])test('snapshot rejects '+name,async()=>{await assert.rejects(readUsingMemory(options));});

import { createHash as compositionHash } from 'node:crypto';
import { readComposedMakepadFontSources } from './support/makepad-font-composition.mjs';
const compositionSha = bytes => compositionHash('sha256').update(bytes).digest('hex');
function compositionFixture() {
 const fontPaths=['src/text/fonts.rs','src/shader/draw_text.rs','src/text/rasterizer.rs'];
 const consumerPaths=['makepad-draw/src/shader/draw_text.rs','makepad-draw/src/text/font.rs','makepad-draw/src/text/loader.rs','makepad-platform/src/hepta_font_consumer.rs','makepad-platform/src/lib.rs','makepad-platform/src/script/res.rs','makepad-platform/src/os/web/web_network.rs'];
 const sources=new Map(fontPaths.map(path=>[`makepad-draw/${path}`,Buffer.from(`fonts:${path}`)]));
 const fontPatch=Buffer.from('pinned font patch'),consumerPatch=Buffer.from('pinned consumer patch');
 const revision='337566c8b25d47f7e4fff6a202157b65bf183330';
 const fontIdentity={upstream:revision,patchSha256:compositionSha(fontPatch),files:fontPaths.map(path=>({path,beforeSha256:compositionSha(`upstream:${path}`),afterSha256:compositionSha(sources.get(`makepad-draw/${path}`))}))};
 const consumerIdentity={upstream:revision,patchSha256:compositionSha(consumerPatch),files:consumerPaths.map(path=>{
  const beforeSha256=path.endsWith('/hepta_font_consumer.rs')?null:compositionSha(sources.get(path)??`upstream:${path}`);
  sources.set(path,Buffer.from(`consumer:${path}`));
  return {path,beforeSha256,afterSha256:compositionSha(sources.get(path))};
 })};
 return {revision,fontIdentity,fontPatch,consumerIdentity,consumerPatch,sources,readSource:async path=>{
  assert.ok(sources.has(path),`Missing source: ${path}`);return sources.get(path);
 }};
}
test('ordered font then consumer overlays retain all original probe sources',async()=>{
 const result=await readComposedMakepadFontSources(compositionFixture());
 assert.deepEqual([...result.keys()],['src/text/fonts.rs','src/shader/draw_text.rs','src/text/rasterizer.rs']);
 assert.equal(result.get('src/shader/draw_text.rs'),'consumer:makepad-draw/src/shader/draw_text.rs');
});
for(const key of ['fontPatch','consumerPatch'])test(`composition rejects tampered ${key}`,async()=>{
 const x=compositionFixture();x[key]=Buffer.from('tampered');await assert.rejects(readComposedMakepadFontSources(x),/Wrong overlay patch bytes/);
});
for(const key of ['fontIdentity','consumerIdentity'])test(`composition rejects wrong ${key} revision`,async()=>{
 const x=compositionFixture();x[key].upstream='wrong';await assert.rejects(readComposedMakepadFontSources(x),/Wrong pinned Makepad revision/);
});
test('composition rejects consumer applied before the font overlay',async()=>{
 const x=compositionFixture();x.consumerIdentity.files[0].beforeSha256=x.fontIdentity.files[1].beforeSha256;
 await assert.rejects(readComposedMakepadFontSources(x),/Wrong ordered overlay preimage/);
});
test('composition rejects an unapplied consumer layer',async()=>{
 const x=compositionFixture();x.sources.set('makepad-draw/src/shader/draw_text.rs',Buffer.from('fonts:src/shader/draw_text.rs'));
 await assert.rejects(readComposedMakepadFontSources(x),/Wrong composed source/);
});
test('composition rejects an unapplied original font layer',async()=>{
 const x=compositionFixture();x.sources.set('makepad-draw/src/text/fonts.rs',Buffer.from('upstream:src/text/fonts.rs'));
 await assert.rejects(readComposedMakepadFontSources(x),/Wrong composed source/);
});
test('composition rejects a missing consumer component',async()=>{
 const x=compositionFixture();x.sources.delete('makepad-platform/src/hepta_font_consumer.rs');
 await assert.rejects(readComposedMakepadFontSources(x),/Missing source/);
});
test('composition rejects an existing-file preimage for the new recorder',async()=>{
 const x=compositionFixture();x.consumerIdentity.files[3].beforeSha256='a'.repeat(64);
 await assert.rejects(readComposedMakepadFontSources(x),/must be a new file/);
});
for(const mutation of ['missing','duplicate','reordered','foreign'])test(`composition rejects ${mutation} path inventory`,async()=>{
 const x=compositionFixture(),files=x.consumerIdentity.files;
 if(mutation==='missing')files.pop();
 if(mutation==='duplicate')files[1]={...files[0]};
 if(mutation==='reordered')[files[0],files[1]]=[files[1],files[0]];
 if(mutation==='foreign')files[0].path='../foreign.rs';
 await assert.rejects(readComposedMakepadFontSources(x));
});
for(const path of compositionFixture().sources.keys())test(`composition rejects changed final source ${path}`,async()=>{
 const x=compositionFixture();x.sources.set(path,Buffer.from('changed final source'));
 await assert.rejects(readComposedMakepadFontSources(x),/Wrong composed source/);
});
