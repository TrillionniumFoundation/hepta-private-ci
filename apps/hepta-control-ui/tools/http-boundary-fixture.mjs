// Real loopback transports for the unchanged SDK reader. There is no Rust owner fixture.
import {createServer} from 'node:http';
import {gzipSync} from 'node:zlib';

export const BODY_LIMIT=262144;
export const RUNTIME_BODY=Buffer.from('{"product":"hepta","status":"unavailable","error":"legacy runtime unavailable"}');
const full=Buffer.alloc(BODY_LIMIT,0x61);
export const MATRIX_CASES=[
 {name:'complete-single',body:RUNTIME_BODY,status:503},
 {name:'complete-split',body:RUNTIME_BODY,status:503},
 {name:'complete-chunked',body:RUNTIME_BODY,status:503},
 {name:'complete-empty',body:Buffer.alloc(0),status:503},
 {name:'complete-at-limit',body:full,status:200},
 {name:'complete-gzip',body:RUNTIME_BODY,status:503},
 {name:'complete-private',body:RUNTIME_BODY,status:200,cacheControl:'private, no-cache'},
 {name:'complete-head',body:Buffer.alloc(0),status:503,method:'HEAD'},
 {name:'complete-chunked-at-limit',body:full,status:200},
 {name:'complete-gzip-at-limit',body:full,status:200},
 {name:'declared-limit',error:'limit',abort:true,noBytes:true},
 {name:'stream-limit',error:'limit',abort:true},
 {name:'gzip-limit',error:'limit',abort:true},
 {name:'truncated',error:'transport'},
 {name:'explicit-abort',error:'cancel',abort:true,cancelAfterBytes:6},
 {name:'preheaders-abort',error:'cancel',abort:true,cancelOnServer:true,noResponse:true},
 {name:'stall',error:'stall',abort:true,deadlineMs:25000},
 {name:'truncated-gzip',error:'transport'},
 {name:'burst-chunked',error:'limit',abort:true},
 {name:'cancel-before-final-byte',error:'cancel',abort:true,cancelAfterBytes:BODY_LIMIT-1},
];
export const HARD_CASES=[
 ...['burst-chunked','burst-gzip','burst-fixed','burst-single-write'].flatMap(name=>Array.from({length:6},(_,repeat)=>({name,error:'limit',abort:true,cap:4096,noBytes:name==='burst-fixed',repeat}))),
 ...Array.from({length:6},(_,repeat)=>({name:'cancel-before-final-byte',error:'cancel',abort:true,cancelAfterBytes:BODY_LIMIT-1,repeat})),
];
const kinds=new Map([...MATRIX_CASES,...HARD_CASES].map(item=>[item.name,item]));
export const pageHtml=Buffer.from('<!doctype html><title>SDK transport boundary control</title><script src="/sdk.js"></script>');

export async function startHttpFixture(script){
 const records=new Map();
 const server=createServer((request,response)=>{
  const url=new URL(request.url,'http://fixture'),name=url.pathname.split('/').at(-1);
  const headers={'Content-Type':'application/octet-stream','Cache-Control':'no-store','Connection':'close','X-Content-Type-Options':'nosniff'};
  if(url.pathname==='/'||url.pathname==='/sdk.js'){
   const bytes=url.pathname==='/'?pageHtml:script;
   response.writeHead(200,{...headers,'Content-Type':url.pathname==='/'?'text/html':'text/javascript','Content-Length':bytes.length});response.end(bytes);return;
  }
  const kind=kinds.get(name);
  if(!url.pathname.startsWith('/control/')||!kind){response.writeHead(404,headers);response.end();return;}
  const record={name,key:url.pathname+url.search,method:request.method,status:kind.status??503,writtenBytes:0,finished:false,closed:false};
  records.set(record.key,record);let timer;
  response.on('error',error=>{record.error=String(error.message).slice(0,256);});
  response.once('finish',()=>{record.finished=true;});
  response.once('close',()=>{record.closed=true;clearTimeout(timer);});
  const write=bytes=>{record.writtenBytes+=bytes.length;return response.write(bytes);};
  const end=bytes=>{if(bytes)record.writtenBytes+=bytes.length;response.end(bytes);};
  const head=extra=>{record.headers={...headers,...extra};response.writeHead(record.status,record.headers);response.flushHeaders();};
  const later=fn=>{timer=setTimeout(()=>{if(!response.destroyed)fn();},30);};
  if(!kind.error){
   const compressed=name.includes('gzip'),chunked=name.includes('chunked');
   const body=compressed?gzipSync(kind.body):kind.body;
   head({...(!chunked?{'Content-Length':name==='complete-head'?BODY_LIMIT+1:body.length}:{}),...(compressed?{'Content-Encoding':'gzip'}:{}),'Cache-Control':kind.cacheControl??'no-store'});
   if(name==='complete-head'){end();return;}
   if(name==='complete-split'||chunked){const split=Math.min(6,body.length);write(body.subarray(0,split));later(()=>end(body.subarray(split)));}
   else end(body);
   return;
  }
  if(name==='preheaders-abort')return;
  if(name==='declared-limit'||name==='burst-fixed'){head({'Content-Length':name==='declared-limit'?BODY_LIMIT+1:8*1024*1024});return;}
  if(name==='stream-limit'){head({});write(Buffer.alloc(BODY_LIMIT/2,0x61));later(()=>write(Buffer.alloc(BODY_LIMIT/2+1,0x62)));return;}
  if(name==='gzip-limit'||name==='burst-gzip'){head({'Content-Encoding':'gzip'});write(gzipSync(Buffer.alloc(name==='gzip-limit'?BODY_LIMIT+1:8*1024*1024,0x61)));return;}
  if(name==='truncated'||name==='truncated-gzip'){
   const compressed=name==='truncated-gzip',body=compressed?gzipSync(RUNTIME_BODY):RUNTIME_BODY;
   head({'Content-Length':body.length+1,...(compressed?{'Content-Encoding':'gzip'}:{})});write(body.subarray(0,6));later(()=>end(body.subarray(6)));return;
  }
  if(name==='explicit-abort'||name==='stall'){head({'Content-Length':RUNTIME_BODY.length});write(RUNTIME_BODY.subarray(0,6));return;}
  if(name==='cancel-before-final-byte'){head({'Content-Length':BODY_LIMIT});write(full.subarray(0,-1));return;}
  if(name==='burst-single-write'){head({});write(Buffer.alloc(8*1024*1024,0x61));return;}
  if(name==='burst-chunked'){
   head({});let left=8*1024*1024;
   const pump=()=>{
    while(left>0&&!response.destroyed){const count=Math.min(64*1024,left);left-=count;if(!write(Buffer.alloc(count,0x61))){response.once('drain',pump);return;}}
   };
   pump();return;
  }
  throw new Error('Unimplemented boundary fixture: '+name);
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 return {origin:'http://127.0.0.1:'+server.address().port,records,async close(){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}};
}
