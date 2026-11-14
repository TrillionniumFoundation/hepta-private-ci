// Synthetic loopback diagnosis using the exact pinned Makepad HTTP methods.
// No UI, actual Rust callback, model, production owner or device qualification.
import {createServer} from 'node:http';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const root=new URL('./',import.meta.url);
const {chromium}=await import(new URL('./playwright/node_modules/playwright-core/index.mjs',root));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const source=await readFile(new URL('upstream-web.js',root),'utf8');
assert.equal(sha(source),'0404897d76bbd81e2225ab62b2fde1c4832e34331706b94c4c00aa71640fe765');
const start=source.indexOf('    network_http_pump(host_key) {');
const end=source.indexOf('    js_network_ws_open(',start);
assert.ok(start>0&&end>start);
const methods=source.slice(start,end);
const body=JSON.stringify({kind:'runtime_unavailable',message:'no real owner is attached',padding:'12345'});
const server=createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname!=='/data'){
  res.setHeader('Content-Type','text/html');
  res.end(`<html><script>class PinnedNetwork{${methods}}window.PinnedNetwork=PinnedNetwork;</script></html>`);
  return;
 }
 const kind=url.searchParams.get('kind');
 const content=kind==='oversize'?'x'.repeat(257):body;
 const headers={'Content-Type':'application/json','Cache-Control':'no-store'};
 if(kind==='empty')headers['Content-Length']='0';
 if(kind==='truncated')headers['Content-Length']=String(Buffer.byteLength(content)+1);
 res.writeHead(kind==='empty'?200:503,headers);
 if(kind==='empty'){res.end();return;}
 res.write(content.slice(0,6));
 if(kind==='abort')return;
 setTimeout(()=>{
  if(res.destroyed)return;
  res.write(content.slice(6));
  setTimeout(()=>{
   if(res.destroyed)return;
   if(kind==='truncated')res.socket?.end();else res.end();
  },20);
 },20);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const modes=[
 ['baseline','browser-153/chrome-linux64/chrome','153.0.8010.12'],
 ['upstream-fixed-diagnostic','browser-157/chrome-headless-shell-linux64/chrome-headless-shell','157.0.8099.0'],
];
const records=[];
try{
 for(const[mode,relative,expectedVersion]of modes){
  const executablePath=new URL(relative,root).pathname;
  const browser=await chromium.launch({headless:true,executablePath});
  try{
   assert.equal(browser.version(),expectedVersion);
   const cdp=await browser.newBrowserCDPSession();
   const identity=await cdp.send('Browser.getVersion');await cdp.detach();
   const executableSha256=sha(await readFile(executablePath));
   for(const kind of ['positive','empty','oversize','truncated','abort'])for(let repeat=0;repeat<2;repeat++){
    const context=await browser.newContext();
    try{
     const page=await context.newPage();await page.goto(origin);
     const native=await context.newCDPSession(page);await native.send('Network.enable');
     const events=[];
     native.on('Network.loadingFinished',e=>events.push({event:'loadingFinished',requestId:e.requestId}));
     native.on('Network.loadingFailed',e=>events.push({event:'loadingFailed',requestId:e.requestId,error:e.errorText,canceled:e.canceled}));
     const relevant=r=>new URL(r.url()).pathname==='/data';
     const terminals=[];const responses=[];
     page.on('requestfinished',r=>{if(relevant(r))terminals.push({event:'requestfinished'});});
     page.on('requestfailed',r=>{if(relevant(r))terminals.push({event:'requestfailed',failure:r.failure()?.errorText});});
     page.on('response',r=>{if(relevant(r.request()))responses.push({status:r.status()});});
     const headers=page.waitForResponse(r=>relevant(r.request()));
     const application=page.evaluate(({kind,repeat})=>new Promise(resolve=>{
      const app=new window.PinnedNetwork();window.activeProbe=app;
      app.network_http_requests=new Map();app.network_http_hosts=new Map();
      app.id_to_key=(lo,hi)=>`${lo}:${hi}`;
      const allocations=new Map();let next=1;const allocate=bytes=>{const ptr=next++;allocations.set(ptr,bytes);return{ptr,len:bytes.length};};
      app.string_to_u8=value=>allocate(new TextEncoder().encode(value));
      app.array_to_u8=value=>allocate(value);
      const record={callbacks:[],controllerAborted:false};
      app.exports={
       wasm_network_http_progress(){},
       wasm_network_http_response(lo,hi,ml,mh,status,hp,hl,bp,bl){record.callbacks.push({kind:'response',status,bytes:bl,body:new TextDecoder().decode(allocations.get(bp))});},
       wasm_network_http_error(lo,hi,ml,mh,ptr,len){record.callbacks.push({kind:'error',message:new TextDecoder().decode(allocations.get(ptr))});},
      };
      const finish=app.network_http_finish.bind(app);
      app.network_http_finish=entry=>{finish(entry);record.controllerAborted=entry.controller.signal.aborted;record.mapSize=app.network_http_requests.size;resolve(record);};
      const entry={request_key:'1:1',request_id_lo:1,request_id_hi:1,metadata_id_lo:0,metadata_id_hi:0,fetch_url:`${location.origin}/data?kind=${kind}&repeat=${repeat}`,method:'GET',headers:{Accept:'application/json'},body:undefined,max_body:256,host_key:location.origin,is_archive:false,is_archive_range:false,tile_keys:'-',state:'queued',controller:null,stall_timer:null,started_at:0,response_bytes:0};
      app.network_http_requests.set(entry.request_key,entry);app.network_http_dispatch(entry);
     }),{kind,repeat});
     await headers;
     if(kind==='abort')await page.evaluate(()=>window.activeProbe.js_network_http_cancel(1,1));
     const observed=await application;
     await page.waitForFunction(()=>window.activeProbe.network_http_requests.size===0);
     // A diagnostic deadline cannot turn a missing terminal event into success.
     const until=Date.now()+2000;while(terminals.length===0&&Date.now()<until)await new Promise(resolve=>setTimeout(resolve,10));
     const row={mode,kind,repeat,identity,executableSha256,application:observed,responses,terminals,native:events,strictCompleted:terminals.length===1&&terminals[0].event==='requestfinished'};
     records.push(row);console.log(JSON.stringify(row));
     assert.equal(observed.callbacks.length,1);assert.equal(observed.mapSize,0);assert.equal(terminals.length,1);
     if(kind==='positive'||kind==='empty'){
      assert.equal(observed.callbacks[0].kind,'response');assert.equal(observed.controllerAborted,false);
      if(mode==='upstream-fixed-diagnostic')assert.equal(row.strictCompleted,true);
     }else{assert.equal(observed.callbacks[0].kind,'error');assert.equal(row.strictCompleted,false);}
     await native.detach();
    }finally{await context.close();}
   }
  }finally{await browser.close();}
 }
 assert.ok(records.some(r=>r.mode==='baseline'&&r.kind==='positive'&&!r.strictCompleted));
}finally{
 server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
 const summary={diagnosticOnly:true,applicationSourceSha256:sha(source),methodSha256:sha(methods),playwright:'1.63.0',records};
 await writeFile(new URL('no-store-reproduction.json',root),JSON.stringify(summary,null,2)+'\n');
}
