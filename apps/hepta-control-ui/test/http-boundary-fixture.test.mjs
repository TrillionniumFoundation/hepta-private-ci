// Qualifies the real transport fixtures, not the browser or synthetic WASM sink.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {connect} from 'node:http2';
import {createHash} from 'node:crypto';
import {BODY_LIMIT,MATRIX_CASES,startHttpFixture} from '../tools/http-boundary-fixture.mjs';
import {startBoundaryProxy} from '../tools/http-boundary-proxy.mjs';
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check){for(let n=0;n<100&&!check();n++)await sleep(10);assert.ok(check());}

test('real fixed chunked gzip HEAD and exact-limit fixtures deliver the declared content',async()=>{
 const fixture=await startHttpFixture(Buffer.from('// SDK fixture'));
 try{
  for(const item of MATRIX_CASES.filter(item=>!item.error)){
   const path='/control/'+item.name+'?attempt=wire';
   const response=await fetch(fixture.origin+path,{method:item.method??'GET'});
   assert.equal(response.status,item.status);
   assert.equal(response.headers.get('cache-control'),item.cacheControl??'no-store');
   const bytes=Buffer.from(await response.arrayBuffer());
   assert.equal(bytes.length,item.body.length);assert.equal(hash(bytes),hash(item.body));
   assert.equal(fixture.records.get(path).finished,true);
  }
 }finally{await fixture.close();}
});

test('truncated cleartext and gzip transfers really close short of Content-Length',async()=>{
 const fixture=await startHttpFixture(Buffer.from('// SDK fixture'));
 try{
  for(const name of ['truncated','truncated-gzip']){
   const path='/control/'+name+'?attempt=wire',response=await fetch(fixture.origin+path);
   await assert.rejects(response.arrayBuffer());
   const record=fixture.records.get(path);
   assert.equal(record.writtenBytes+1,record.headers['Content-Length']);
   assert.equal(response.headers.get('cache-control'),'no-store');
  }
 }finally{await fixture.close();}
});

test('overflow fixtures remain incomplete until an actual caller aborts',async()=>{
 const fixture=await startHttpFixture(Buffer.from('// SDK fixture'));
 try{
  for(const name of ['declared-limit','stream-limit','gzip-limit','burst-chunked','burst-gzip','burst-fixed','burst-single-write']){
   const path='/control/'+name+'?attempt=wire',controller=new AbortController();
   const response=await fetch(fixture.origin+path,{signal:controller.signal});
   let bytes=0;const reader=response.body.getReader();
   if(name==='declared-limit'||name==='burst-fixed')assert.ok(Number(response.headers.get('content-length'))>BODY_LIMIT);
   else while(bytes<=BODY_LIMIT){const item=await reader.read();assert.equal(item.done,false);bytes+=item.value.length;}
   const record=fixture.records.get(path);assert.equal(record.finished,false);
   if(name==='declared-limit'||name==='burst-fixed')assert.equal(record.writtenBytes,0);
   controller.abort();
   await assert.rejects(reader.read());
   await until(()=>record.closed);
  }
 }finally{await fixture.close();}
});

test('headerless and last-byte controls wait for an actual cancellation',async()=>{
 const fixture=await startHttpFixture(Buffer.from('// SDK fixture'));
 try{
  const path='/control/preheaders-abort?attempt=wire',controller=new AbortController();
  const request=fetch(fixture.origin+path,{signal:controller.signal});
  await until(()=>fixture.records.has(path));controller.abort();await assert.rejects(request);
  const last='/control/cancel-before-final-byte?attempt=wire',second=new AbortController();
  const response=await fetch(fixture.origin+last,{signal:second.signal}),reader=response.body.getReader();
  let bytes=0;while(bytes<BODY_LIMIT-1){const item=await reader.read();assert.equal(item.done,false);bytes+=item.value.length;}
  assert.equal(bytes,BODY_LIMIT-1);assert.equal(fixture.records.get(last).finished,false);
  second.abort();await assert.rejects(reader.read());
 }finally{await fixture.close();}
});

test('the HTTPS proxy negotiates real HTTP/2 and sends the false one-byte framing',async()=>{
 const fixture=await startBoundaryProxy(Buffer.from('// SDK fixture'));
 try{
  for(const wire of ['open','complete']){
  // A malformed response can close the HTTP/2 session as well as its stream.
  // Each framing variant therefore owns a real, independently negotiated session.
  const client=connect(fixture.proxy.server,{ca:fixture.certificate,servername:'localhost'});
  try{
  await new Promise((resolve,reject)=>{client.once('connect',resolve);client.once('error',reject);});
  assert.equal(client.alpnProtocol,'h2');
  const path='/control/h2-small-length?attempt=wire&wire='+wire,stream=client.request({':method':'GET',':scheme':'http',':authority':'127.0.0.1:4175',':path':path});
  let headers,streamError;
  stream.on('response',value=>{headers=value;});stream.on('data',()=>{});stream.on('error',error=>{streamError=error;});
  stream.end();await new Promise(resolve=>stream.once('close',resolve));
  assert.ok(headers,'response headers for '+wire);
  assert.equal(headers['content-length'],'1');assert.equal(headers['cache-control'],'no-store');
  const record=fixture.records.get(path);assert.equal(record.declaredBytes,1);assert.equal(record.writtenBytes,65536);
  // Node rejects this malformed response. Chromium's own handling is independently
  // measured by the required browser controls, never inferred from this client.
  assert.ok(streamError);
  assert.equal(record.complete,wire==='complete');
  }finally{client.destroy();}
  }
 }finally{await fixture.close();}
});
