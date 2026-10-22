// Optional source-bound Rust observations. No acceptance fault is suppressed.
import assert from 'node:assert/strict';
const digest=/^[0-9a-f]{64}$/;
const uint=value=>Number.isSafeInteger(value)&&value>=0;
const decimal=value=>typeof value==='string'&&/^(0|[1-9][0-9]{0,19})$/.test(value)&&BigInt(value)<=0xffffffffffffffffn;
const pathOf=value=>{
 assert.equal(typeof value,'string');assert.match(value,/^(?:[0-9a-f]{2}){1,2048}$/);
 const bytes=Buffer.from(value,'hex'),path=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
 assert.equal(Buffer.from(path).toString('hex'),value);return path;
};
export function validateConsumer(snapshot,delivery,{nonce,requiredUsePaths,manifest}){
 try{
  assert.ok(uint(nonce)&&nonce>0&&nonce<=0xffffffff);
  assert.ok(snapshot&&snapshot.version===2&&snapshot.nonce===nonce&&snapshot.sealed===true&&snapshot.overflow===false);
  assert.ok(uint(snapshot.hashedBytes)&&snapshot.hashedBytes<=256*1024*1024);
  assert.ok(Array.isArray(snapshot.events)&&snapshot.events.length>0&&snapshot.events.length<=512);
  assert.ok(Array.isArray(requiredUsePaths)&&requiredUsePaths.length>0&&requiredUsePaths.length<=32);
  assert.equal(new Set(requiredUsePaths).size,requiredUsePaths.length);
  assert.ok(manifest?.threads===false&&manifest.fixtures===false&&manifest.fontConsumerResources);
  const mappings=Object.entries(manifest.fontConsumerResources);
  assert.ok(mappings.length>0&&mappings.length<=32);
  assert.equal(new Set(mappings.map(([,value])=>value.absolutePath)).size,mappings.length);
  for(const [path,value]of mappings){
   const pin=manifest.files[path.slice(1)];assert.ok(pin);
   assert.equal(value.dependencyPath,path.slice(1));assert.equal(value.bytes,pin.bytes);assert.equal(value.sha256,pin.sha256);
  }
  const requests=new Map(),mappedRequests=new Set(),publicRequests=new Set(),fontRequests=new Map();
  const adoptions=new Map(),definitions=new Map(),attempts=new Map(),parses=new Map(),draws=new Map(),drawKeys=new Set();
  for(const record of delivery.records){
   assert.ok(decimal(record.request));assert.ok(!requests.has(record.request));requests.set(record.request,record);
  }
  for(const [index,event]of snapshot.events.entries()){
   assert.equal(event.seq,index+1);
   if(event.stage==='http-response'){
    // The pinned Web shim allocates a transport ID and maps it back to the
    // caller's ID before emitting its response. Observe that actual boundary;
    // neither masking bits nor matching paths proves which request was adopted.
    assert.ok(decimal(event.request)&&decimal(event.publicRequest));
    assert.ok(!mappedRequests.has(event.request)&&!publicRequests.has(event.publicRequest));
    mappedRequests.add(event.request);publicRequests.add(event.publicRequest);
    const original=requests.get(event.request);
    if(original)fontRequests.set(event.publicRequest,original);
   }else if(event.stage==='adopt'){
    assert.ok(decimal(event.request)&&!adoptions.has(event.request));
    const original=fontRequests.get(event.request);assert.ok(original);
    const expected=manifest.fontConsumerResources[original.path];assert.ok(expected);
    assert.equal(pathOf(event.pathHex),expected.absolutePath);
    assert.equal(original.bytes,expected.bytes);assert.equal(original.sha256,expected.sha256);
    assert.ok(uint(event.bytes)&&digest.test(event.sha256));
    assert.equal(event.bytes,original.bytes);assert.equal(event.sha256,original.sha256);
    adoptions.set(event.request,{...event,path:pathOf(event.pathHex),original});
   }else if(event.stage==='define'){
    assert.ok(decimal(event.font)&&!definitions.has(event.font));
    const path=pathOf(event.pathHex);
    const matches=[...adoptions.values()].filter(item=>item.path===path);
    assert.equal(matches.length,1);const adoption=matches[0];
    assert.equal(event.bytes,adoption.bytes);assert.equal(event.sha256,adoption.sha256);
    definitions.set(event.font,{...event,adoption});
   }else if(event.stage==='parse-start'){
    assert.ok(decimal(event.font)&&definitions.has(event.font)&&!attempts.has(event.font));
    attempts.set(event.font,event);
   }else if(event.stage==='parse'){
    assert.ok(decimal(event.font)&&!parses.has(event.font));
    assert.ok(attempts.has(event.font));
    const definition=definitions.get(event.font);assert.ok(definition);
    assert.equal(event.bytes,definition.bytes);assert.equal(event.sha256,definition.sha256);
    parses.set(event.font,{...event,definition});
   }else if(event.stage==='draw'){
    assert.ok(decimal(event.font)&&parses.has(event.font));
    assert.ok(uint(event.glyph)&&event.glyph>0&&event.glyph<=65535);
    assert.ok(event.kind===1||event.kind===2);
    const key=event.font+':'+event.glyph+':'+event.kind;assert.ok(!drawKeys.has(key));drawKeys.add(key);
    if(!draws.has(event.font))draws.set(event.font,[]);draws.get(event.font).push(event);
   }else assert.fail('Unknown Rust consumer event');
  }
  assert.equal(fontRequests.size,requests.size);
  assert.equal(adoptions.size,requests.size);
  for(const font of attempts.keys())assert.ok(parses.has(font),'Actual parser attempt did not succeed');
  const observations=[...adoptions.values()].map(adoption=>{
   const fonts=[...definitions.values()].filter(item=>item.adoption===adoption);
   return {path:adoption.original.path,request:adoption.original.request,publicRequest:adoption.request,bytes:adoption.bytes,sha256:adoption.sha256,
    adopted:true,defined:fonts.length>0,parsed:fonts.some(font=>parses.has(font.font)),
    naturallyEmitted:fonts.some(font=>draws.has(font.font)),fontIds:fonts.map(font=>font.font)};
  });
  for(const path of requiredUsePaths){
   const match=observations.filter(item=>item.path===path);assert.equal(match.length,1);
   assert.ok(match[0].parsed&&match[0].naturallyEmitted,'Required font was not naturally consumed');
  }
  return {passed:true,diagnosticOnly:true,scope:'Request-bound Rust adoption and observed natural glyph-instance emission; not GPU presentation or full font coverage',requiredUsePaths,observations};
 }catch(error){return {passed:false,diagnosticOnly:true,error:String(error).slice(0,512)};}
}

// Called through the debugger's private remote object, not a page/window sink.
// Rust exports accept enable/seal/read operations only; none inject positive events.
export async function readConsumerSnapshot(session,objectId,nonce){
 const result=await session.send('Runtime.callFunctionOn',{
  objectId,arguments:[{value:nonce}],returnByValue:true,silent:true,
  functionDeclaration:`function(nonce){
   const e=this.exports;
   if(e.hepta_font_consumer_seal(nonce)!==1)throw new Error('Rust consumer seal failed');
   const rawPtr=e.hepta_font_consumer_snapshot_ptr(nonce),rawLen=e.hepta_font_consumer_snapshot_len(nonce);
   // WASM i32 results may be signed; reject non-integers before conversion.
   if(!Number.isInteger(rawPtr)||rawPtr< -0x80000000||rawPtr>0xffffffff||!Number.isInteger(rawLen)||rawLen<=0||rawLen>256*1024)throw new Error('Invalid Rust snapshot integers');
   const ptr=rawPtr>>>0,len=rawLen,end=ptr+len;
   // Acquire only AFTER every WASM call (any of those could grow memory).
   // This synchronous function performs no further WASM call, await, or page
   // callback before copying. Non-shared memory cannot grow concurrently.
   const memory=this.memory.buffer;
   if(!(memory instanceof ArrayBuffer)||!ptr||!Number.isSafeInteger(end)||end>0x100000000||end>memory.byteLength)throw new Error('Invalid Rust snapshot bounds');
   const copy=new Uint8Array(memory,ptr,len).slice();
   return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(copy));
  }`,
 });
 if(result.exceptionDetails||!result.result?.value)throw new Error('Rust consumer snapshot unavailable');
 return result.result.value;
}

// close() always preserves an existing product failure, but a healthy observed
// case cannot stay green when the final optional consumer proof is invalid.
export function assertOptionalOutcome(passed,{priorFailure=false}={}){
 if(!passed&&!priorFailure)throw new Error('SDK/Rust font consumer diagnostic failed');
}
