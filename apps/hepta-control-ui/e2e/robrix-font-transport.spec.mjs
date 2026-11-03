// Actual pinned SDK reader, real HTTP controls, synthetic WASM export sink.
// This never substitutes for Rust font adoption or product pixel evidence.
import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {loadArtifactSnapshot} from '../tools/owned-artifact-lease.mjs';
import {startControlServer,CONTROL_BODY} from '../tools/font-transport-fixture.mjs';
import {recordProductBrowser} from '../tools/font-diagnostic-browser-identity.mjs';
test('bounded SDK stream terminal controls',async({page,browser},testInfo)=>{
 const productQualification=testInfo.project.metadata.productBrowserQualification===true;
 test.skip((!testInfo.project.metadata.diagnosticOnly&&!productQualification)||testInfo.project.metadata.fontDeliveryObserver,'Run identical transport controls once per browser, in untouched projects');
 expect(browser.version()).toBe(testInfo.project.metadata.expectedBrowser);
 const browserIdentity=await recordProductBrowser(browser,testInfo);
 const snapshot=await loadArtifactSnapshot(new URL('../dist/',import.meta.url).pathname);
 const server=await startControlServer(snapshot),results=[];
 const controls=[
  ...['complete','revalidated','truncated','abort','declared-limit','stream-limit'].map(kind=>({kind,cache:null})),
  ...['truncated','abort','declared-limit','stream-limit'].map(kind=>({kind,cache:'private'})),
 ];
 try{
  for(const {kind,cache} of controls){
   await page.goto(server.origin+'/probe');
   const terminal=new Promise(resolve=>{
    const finish=request=>{if(!request.url().includes('/control?'))return;cleanup();resolve({event:'finished'});};
    const fail=request=>{if(!request.url().includes('/control?'))return;cleanup();resolve({event:'failed',error:request.failure()?.errorText});};
    const cleanup=()=>{page.off('requestfinished',finish);page.off('requestfailed',fail);};
    page.on('requestfinished',finish);page.on('requestfailed',fail);
   });
   const headers=page.waitForResponse(response=>response.url().includes('/control?'));
   const application=page.evaluate(async({kind,cache})=>{
    const {WasmWebBrowser}=await import('/makepad_platform/web.js');
    const host=Object.create(WasmWebBrowser.prototype);let body,result,finish,lastString;
    const done=new Promise(resolve=>finish=resolve);
    Object.assign(host,{webgl_context_lost:false,network_http_requests:new Map(),network_http_hosts:new Map(),
     string_to_u8:value=>{lastString=value;return{ptr:0,len:0};},array_to_u8:bytes=>{body=bytes;return{ptr:1,len:bytes.length};},
     exports:{wasm_network_http_progress(){},wasm_network_http_response(){result={delivered:true};},wasm_network_http_error(){result={delivered:false,error:lastString.slice(0,200)};}},
    });
    const original=host.network_http_finish;
    host.network_http_finish=function(entry){original.call(this,entry);finish();};
    const entry={request_key:'diagnostic',request_id_lo:1,request_id_hi:0,metadata_id_lo:0,metadata_id_hi:0,
     fetch_url:new URL('/control?kind='+kind+(cache?'&cache='+cache:''),location.href).href,method:'GET',headers:new Headers(),body:undefined,
     max_body:128,host_key:location.origin,is_archive:false,is_archive_range:false,tile_keys:'-',state:'queued',
     controller:null,stall_timer:null,response_bytes:0};
    window.__heptaControlEntry=entry;host.network_http_requests.set(entry.request_key,entry);host.network_http_dispatch(entry);
    await done;
    if(result.delivered){result.bytes=body.length;result.sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',body)),v=>v.toString(16).padStart(2,'0')).join('');}
    return {...result,finalState:entry.state,responseBytes:entry.response_bytes};
   },{kind,cache});
   const response=await headers,cacheControl=response.headers()['cache-control'];
   expect(cacheControl).toBe(cache==='private'||kind==='revalidated'?'private, no-cache':'no-store');
   if(kind==='abort')await page.evaluate(()=>window.__heptaControlEntry.controller.abort('diagnostic explicit abort'));
   const app=await application;let timer;
   const native=await Promise.race([terminal,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Native terminal observation missing')),3000);})]).finally(()=>clearTimeout(timer));
   results.push({kind,cacheControl,app,native});
   if(kind==='complete'||kind==='revalidated'){
    expect(app).toEqual({delivered:true,bytes:CONTROL_BODY.length,sha256:createHash('sha256').update(CONTROL_BODY).digest('hex'),finalState:'done',responseBytes:CONTROL_BODY.length});
    // Baseline result remains recorded, never treated as successful transport.
    if(productQualification||kind==='revalidated'||testInfo.project.name.startsWith('fixed-'))expect(native).toEqual({event:'finished'});
   }else{
    const {error,...state}=app;expect(state).toEqual({delivered:false,finalState:'done',responseBytes:0});
    expect(error).toBeTruthy();
    if(kind==='declared-limit'||kind==='stream-limit')expect(error).toBe('response body exceeds configured limit');
    if(kind==='truncated'||kind==='abort')expect(native.event).toBe('failed');
   }
  }
 }finally{
  await server.close();
  await writeFile(testInfo.outputPath('sdk-control-results.json'),JSON.stringify({diagnosticOnly:!productQualification,transportControlOnly:true,scope:'synthetic export sink; not Rust font adoption',browser:browser.version(),browserIdentity,manifestSha256:snapshot.manifestDigest,results,server:server.records},null,2)+'\n');
 }
});
