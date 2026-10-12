import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateConsumer,readConsumerSnapshot,assertOptionalOutcome} from '../tools/font-consumer-diagnostic.mjs';
const path='/makepad_widgets/resources/IBMPlexSans-Text.ttf',abs='/source/font.ttf',hash='a'.repeat(64);
function sample(){
 const snapshot={version:1,nonce:17,sealed:true,overflow:false,hashedBytes:30,events:[
  {seq:1,stage:'adopt',request:'18446744073709551615',pathHex:Buffer.from(abs).toString('hex'),bytes:10,sha256:hash},
  {seq:2,stage:'define',font:'18446744073709551614',pathHex:Buffer.from(abs).toString('hex'),bytes:10,sha256:hash},
  {seq:3,stage:'parse-start',font:'18446744073709551614'},
  {seq:4,stage:'parse',font:'18446744073709551614',bytes:10,sha256:hash},
  {seq:5,stage:'draw',font:'18446744073709551614',glyph:38,kind:1},
 ]};
 const delivery={records:[{path,request:'18446744073709551615',bytes:10,sha256:hash}]};
 return bindManifest({snapshot,delivery,options:{nonce:17,requiredUsePaths:[path]}});
}
function bindManifest(x){
 const resources=Object.fromEntries(x.delivery.records.map(record=>{
  const event=x.snapshot.events.find(event=>event.stage==='adopt'&&event.request===record.request);
  return [record.path,{absolutePath:Buffer.from(event.pathHex,'hex').toString(),dependencyPath:record.path.slice(1),bytes:record.bytes,sha256:record.sha256}];
 }));
 x.options.manifest={threads:false,fixtures:false,fontConsumerResources:resources,files:Object.fromEntries(x.delivery.records.map(r=>[r.path.slice(1),{bytes:r.bytes,sha256:r.sha256}]))};
 return x;
}
const validate=x=>validateConsumer(x.snapshot,x.delivery,x.options);
test('exact request digest parser and natural-instance chain passes scoped diagnostic',()=>{
 const result=validate(sample());assert.equal(result.passed,true);assert.equal(result.observations[0].naturallyEmitted,true);
});
test('adoption alone is not parsing or required use',()=>{
 const x=sample();x.snapshot.events=x.snapshot.events.slice(0,1);assert.equal(validate(x).passed,false);
});
test('parsed but never naturally emitted fails required use',()=>{
 const x=sample();x.snapshot.events.pop();assert.equal(validate(x).passed,false);
});
test('no packaged-font blanket use requirement',()=>{
 const x=sample();x.delivery.records.push({path:'/optional.ttf',request:'5',bytes:3,sha256:hash});
 x.snapshot.events.push({seq:6,stage:'adopt',request:'5',pathHex:Buffer.from('/source/optional.ttf').toString('hex'),bytes:3,sha256:hash});
 bindManifest(x);const r=validate(x);assert.equal(r.passed,true);assert.equal(r.observations[1].parsed,false);assert.equal(r.observations[1].naturallyEmitted,false);
});
test('an unfinished actual parser attempt fails even outside required-use subset',()=>{
 const x=sample(),pathHex=Buffer.from('/source/optional.ttf').toString('hex');
 x.delivery.records.push({path:'/optional.ttf',request:'5',bytes:3,sha256:hash});
 x.snapshot.events.push(
  {seq:6,stage:'adopt',request:'5',pathHex,bytes:3,sha256:hash},
  {seq:7,stage:'define',font:'8',pathHex,bytes:3,sha256:hash},
  {seq:8,stage:'parse-start',font:'8'},
 );
 bindManifest(x);assert.equal(validate(x).passed,false);
});
for(const [name,change]of [
 ['stale nonce',x=>x.snapshot.nonce++],['overflow',x=>x.snapshot.overflow=true],['unsealed',x=>x.snapshot.sealed=false],
 ['wrong adoption hash',x=>x.snapshot.events[0].sha256='b'.repeat(64)],['wrong parser hash',x=>x.snapshot.events[3].sha256='b'.repeat(64)],
 ['wrong font',x=>x.snapshot.events[4].font='19'],['missing glyph',x=>x.snapshot.events[4].glyph=0],
 ['wrong resource',x=>x.snapshot.events[1].pathHex=Buffer.from('/other.ttf').toString('hex')],
 ['reused sequence',x=>x.snapshot.events[4].seq=3],['duplicate adoption',x=>x.snapshot.events.push({...x.snapshot.events[0],seq:6})],
 ['duplicate parser',x=>x.snapshot.events.push({...x.snapshot.events[3],seq:6})],['duplicate draw',x=>x.snapshot.events.push({...x.snapshot.events[4],seq:6})],
 ['wrong request',x=>x.snapshot.events[0].request='42'],['lost adoption',x=>x.snapshot.events.splice(0,1)],
 ['parse missing',x=>{x.snapshot.events.splice(3,1);x.snapshot.events[3].seq=4;}],
 ['early draw',x=>{[x.snapshot.events[3],x.snapshot.events[4]]=[x.snapshot.events[4],x.snapshot.events[3]];x.snapshot.events[3].seq=4;x.snapshot.events[4].seq=5;}],
 ['unknown event',x=>x.snapshot.events[4].stage='forged'],['no required scope',x=>x.options.requiredUsePaths=[]],
 ['duplicate delivery request',x=>x.delivery.records.push({...x.delivery.records[0]})],
])test(name+' is rejected',()=>{const x=sample();change(x);assert.equal(validate(x).passed,false);});
test('snapshot reads only private remote object and fails on Rust/remote error',async()=>{
 let call;const session={async send(method,args){call={method,args};return {result:{value:sample().snapshot}};}};
 assert.equal((await readConsumerSnapshot(session,'private-handle',17)).nonce,17);
 assert.equal(call.method,'Runtime.callFunctionOn');assert.equal(call.args.objectId,'private-handle');
 assert.ok(!call.args.functionDeclaration.includes('console'));
 await assert.rejects(readConsumerSnapshot({async send(){return{exceptionDetails:{text:'trapped'}};}},'private',17));
});

test('coordinated adoption/definition absolute path change cannot rename expected resource',()=>{
 const x=sample();for(const index of [0,1])x.snapshot.events[index].pathHex=Buffer.from('/other.ttf').toString('hex');
 assert.equal(validate(x).passed,false);
});
test('changing both delivered and consumer digest cannot bypass immutable manifest',()=>{
 const x=sample();x.delivery.records[0].sha256='b'.repeat(64);
 for(const index of [0,1,3])x.snapshot.events[index].sha256='b'.repeat(64);
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
