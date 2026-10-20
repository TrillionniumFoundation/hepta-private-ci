// Required transport regression, separate from real Rust UI/gateway qualification.
// The SDK methods are taken byte-for-byte from the freshly built shipping artifact.
// Only the WASM exports are synthetic; no replacement fetch reader, tee, or cache override.
import {chromium} from 'playwright';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pinnedChromiumUse} from './pinned-chromium.mjs';
import {recordPinnedChromium} from './font-diagnostic-browser-identity.mjs';
import {BODY_LIMIT,MATRIX_CASES,HARD_CASES,startHttpFixture} from './http-boundary-fixture.mjs';
import {startBoundaryProxy} from './http-boundary-proxy.mjs';

const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const root=process.cwd(),output=resolve(root,'test-results/http-boundaries');
await mkdir(output,{recursive:true});
const report={schema:'hepta.sdk.http-boundaries.v1',scope:'Real HTTP and exact shipping SDK methods with synthetic WASM exports; does not qualify Rust rendering, owner attachment, or gateway status',required:true,passed:false,bodyLimit:BODY_LIMIT,stallTimeoutMs:20000,nativeObservationMs:1500,matrixRequired:60,hardNegativeRequired:36,results:[]};
let browser,http,proxy;
const within=async(promise,ms)=>{
 let timer;
 try{return await Promise.race([promise.then(value=>({settled:true,value:value instanceof Error?{error:String(value)}:value}),error=>({settled:true,error:String(error)})),new Promise(resolve=>{timer=setTimeout(()=>resolve({settled:false}),ms);})]);}
 finally{clearTimeout(timer);}
};

async function qualifyBrowser(value,directory){
 await mkdir(directory,{recursive:true});
 await recordPinnedChromium(value,{project:{name:'chromium',metadata:{pinnedChromium:true,diagnosticOnly:false}},outputPath:name=>join(directory,name)});
}

async function runCase(config,repeat,suite,origin,serverRecords){
 const page=await browser.newPage(),events=[],observerErrors=[];
 const url=new URL('/control/'+config.name,origin);url.searchParams.set('attempt',suite+'-'+repeat);
 if(config.wire)url.searchParams.set('wire',config.wire);
 const started=performance.now(),milliseconds=()=>Math.round(performance.now()-started);
 const result={suite,name:config.name,repeat,cap:config.cap??BODY_LIMIT,url:url.href,passed:false};
 let response,requestId,protocol,receivedBytes=0,cancelScheduled=false,cancelTask,nativeResolve,session;
 const nativeTerminal=new Promise(resolve=>{nativeResolve=resolve;});
 const record=event=>{if(events.length>=512){if(!observerErrors.includes('native event limit exceeded'))observerErrors.push('native event limit exceeded');return;}events.push({ms:milliseconds(),...event});};
 const cancel=()=>{if(cancelScheduled)return;cancelScheduled=true;cancelTask=page.evaluate(()=>window.boundaryHost.js_network_http_cancel(1,0)).catch(error=>observerErrors.push(String(error).slice(0,512)));};
 page.on('response',value=>{if(value.url()===url.href){response=value;record({kind:'response',status:value.status(),headers:value.headers()});}});
 page.on('requestfinished',request=>{if(request.url()===url.href){const event={kind:'requestfinished'};record(event);nativeResolve(event);}});
 page.on('requestfailed',request=>{if(request.url()===url.href){const event={kind:'requestfailed',error:request.failure()?.errorText};record(event);nativeResolve(event);}});
 try{
  session=await page.context().newCDPSession(page);await session.send('Network.enable');
  session.on('Network.requestWillBeSent',event=>{if(event.request.url===url.href){requestId=event.requestId;record({kind:'cdp-request',requestId});}});
  session.on('Network.responseReceived',event=>{if(event.requestId===requestId){protocol=event.response.protocol;record({kind:'cdp-response',status:event.response.status,protocol});}});
  session.on('Network.dataReceived',event=>{
   if(event.requestId!==requestId)return;receivedBytes+=event.dataLength;
   record({kind:'cdp-data',dataLength:event.dataLength,encodedDataLength:event.encodedDataLength});
   if(config.cancelAfterBytes&&receivedBytes>=config.cancelAfterBytes)cancel();
  });
  session.on('Network.loadingFinished',event=>{if(event.requestId===requestId)record({kind:'cdp-finished',encodedDataLength:event.encodedDataLength});});
  session.on('Network.loadingFailed',event=>{if(event.requestId===requestId)record({kind:'cdp-failed',error:event.errorText,canceled:event.canceled});});
  await page.goto(origin,{waitUntil:'load',timeout:10000});
  await page.evaluate(({url,method,cap,cancelAfterMs})=>{
   const host=new window.PinnedNetwork();let bytes,lastString;
   window.boundaryResults=[];window.boundaryHost=host;
   Object.assign(host,{
    webgl_context_lost:false,network_http_requests:new Map(),network_http_hosts:new Map(),
    id_to_key:(lo,hi)=>lo+':'+hi,
    string_to_u8:value=>{lastString=value;return {ptr:0,len:0};},
    array_to_u8:value=>{bytes=value;window.boundaryBytes=value;return {ptr:0,len:value.length};},
    exports:{
     wasm_network_http_progress(){},
     wasm_network_http_response(lo,hi,mlo,mhi,status){window.boundaryResults.push({kind:'response',status,bytes:bytes.length});},
     wasm_network_http_error(){window.boundaryResults.push({kind:'error',error:lastString});},
    },
   });
   const entry={request_key:'1:0',request_id_lo:1,request_id_hi:0,metadata_id_lo:0,metadata_id_hi:0,fetch_url:url,method,headers:new Headers(),body:undefined,max_body:cap,host_key:location.origin,is_archive:false,is_archive_range:false,tile_keys:'-',state:'queued',controller:null,stall_timer:null,response_bytes:0};
   window.boundaryEntry=entry;host.network_http_requests.set(entry.request_key,entry);host.network_http_dispatch(entry);
   if(cancelAfterMs)setTimeout(()=>host.js_network_http_cancel(1,0),cancelAfterMs);
  },{url:url.href,method:config.method??'GET',cap:result.cap,cancelAfterMs:config.cancelAfterMs});
  if(config.cancelOnServer){
   for(let attempt=0;attempt<100&&!serverRecords.has(url.pathname+url.search);attempt++)await new Promise(resolve=>setTimeout(resolve,10));
   if(!serverRecords.has(url.pathname+url.search))throw new Error('Cancellation control did not reach the real server');
   cancel();await cancelTask;
  }
  await page.waitForFunction(()=>window.boundaryEntry.state==='done'&&window.boundaryResults.length>0,null,{timeout:config.deadlineMs??5000});
  result.sdkSettledMs=milliseconds();
  if(cancelTask)await cancelTask;
  result.nativeTerminal=await within(nativeTerminal,1500);
  result.responseFinished=response?await within(response.finished(),1500):{responseObserved:false};
  result.application=await page.evaluate(async()=>({
   results:window.boundaryResults,
   exportedBodySha256:window.boundaryBytes?Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',window.boundaryBytes))).map(byte=>byte.toString(16).padStart(2,'0')).join(''):null,
   state:window.boundaryEntry.state,responseBytes:window.boundaryEntry.response_bytes,
   controllerAborted:window.boundaryEntry.controller.signal.aborted,
   activeRequests:window.boundaryHost.network_http_requests.size,stallTimerCleared:window.boundaryEntry.stall_timer===null,
  }));
  result.protocol=protocol;result.receivedBytes=receivedBytes;result.cancelScheduled=cancelScheduled;
  result.cacheControl=response?.headers()['cache-control'];
  const sdkResponses=result.application.results.filter(item=>item.kind==='response'),sdkErrors=result.application.results.filter(item=>item.kind==='error');
  const checks={cleanup:result.application.state==='done'&&result.application.activeRequests===0&&result.application.stallTimerCleared,observers:observerErrors.length===0};
  if(!config.error){
   checks.body=sdkErrors.length===0&&sdkResponses.length===1&&sdkResponses[0].status===config.status&&sdkResponses[0].bytes===config.body.length&&result.application.exportedBodySha256===hash(config.body);
   checks.native=result.nativeTerminal.value?.kind==='requestfinished'&&result.responseFinished.settled&&result.responseFinished.value===null;
   checks.notAborted=!result.application.controllerAborted;
  }else{
   checks.noBody=sdkResponses.length===0&&sdkErrors.length===1&&result.application.exportedBodySha256===null&&result.application.responseBytes===0;
   checks.native=result.nativeTerminal.value?.kind==='requestfailed'&&typeof result.nativeTerminal.value.error==='string'&&result.nativeTerminal.value.error.length>0;
   const error=String(sdkErrors[0]?.error??'');
   checks.cause=config.error==='limit'?/response body exceeds configured limit/.test(error):config.error==='cancel'?/abort/i.test(error):config.error==='stall'?/stalled for 20 seconds/.test(error):/^(?:TypeError(?::|$)|response body exceeds configured limit$)/.test(error);
   if(config.abort)checks.aborted=result.application.controllerAborted;
   if(config.cancelAfterBytes)checks.bodyBoundary=cancelScheduled&&receivedBytes>=config.cancelAfterBytes;
   if(config.name==='stall')checks.originalDeadline=result.sdkSettledMs>=19900;
  }
  checks.cache=config.noResponse?!response:result.cacheControl===(config.cacheControl??'no-store');
  const server=serverRecords.get(url.pathname+url.search);result.server=server?{...server}:null;
  checks.realServer=!!server;
  if(config.noBytes)checks.noServerBody=server?.writtenBytes===0;
  if(config.protocol){
   checks.actualProtocol=protocol===config.protocol;checks.falseLength=server?.declaredBytes===1&&server?.writtenBytes===65536&&response?.headers()['content-length']==='1';
   checks.status=response?.status()===503;
   // A completed wire transfer can finish before the SDK rejects its body size.
   // Incomplete controls still require native failure; no successful SDK response is allowed.
   if(config.wire==='complete')checks.native=checks.native||(server?.finished===true&&result.nativeTerminal.value?.kind==='requestfinished'&&result.responseFinished.settled&&result.responseFinished.value===null);
  }
  result.checks=checks;result.passed=Object.values(checks).every(Boolean);
 }catch(error){result.error=String(error?.stack??error).slice(0,4096);}
 finally{
  result.beforeTeardown=events.map(event=>({...event}));result.observerErrors=[...observerErrors];
  await page.close().catch(error=>{result.cleanupError=String(error).slice(0,512);result.passed=false;});
  result.afterTeardownEvents=events.slice(result.beforeTeardown.length);
  if(session)await session.detach().catch(()=>{});
  result.elapsedMs=milliseconds();report.results.push(result);
  await writeFile(join(output,'results.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({suite,name:config.name,repeat,passed:result.passed,checks:result.checks,error:result.error}));
 }
}

try{
 const asset=await readFile(join(root,'dist/makepad_platform/web.js')),manifestBytes=await readFile(join(root,'dist/build-manifest.json')),manifest=JSON.parse(manifestBytes);
 const pin=manifest.files['makepad_platform/web.js'];
 if(manifest.fixtures!==false)throw new Error('Boundary qualification requires the ordinary product build before fixture replacement');
 if(pin.bytes!==asset.length||pin.sha256!==hash(asset))throw new Error('Shipping SDK does not match the built manifest');
 if(manifest.packagerSource!=='337566c8b25d47f7e4fff6a202157b65bf183330')throw new Error('Unreviewed SDK revision');
 const source=asset.toString('utf8'),start=source.indexOf('    network_http_dispatch(entry) {'),cancel=source.indexOf('    js_network_http_cancel(request_id_lo, request_id_hi) {',start),end=source.indexOf('\n    }\n',cancel)+7;
 if(start<0||cancel<start||end<=cancel)throw new Error('SDK method boundary changed');
 const methods=source.slice(start,end);
 if(hash(methods)!=='a688eaa4ff6883817fa519b8f7efa3935e781dc47ac89e42808e3b2e5d4acec7')throw new Error('Shipping SDK reader changed; re-review its stream/cancel/limit contract');
 const script=Buffer.from('class PinnedNetwork {\n'+methods+'\n}\nwindow.PinnedNetwork=PinnedNetwork;\n');
 await writeFile(join(output,'build-manifest.json'),manifestBytes);
 await writeFile(join(output,'sdk-method-fixture.js'),script);
 report.source={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),tree:execFileSync('git',['rev-parse','HEAD^{tree}'],{encoding:'utf8'}).trim(),sdkAssetSha256:hash(asset),sdkMethodsSha256:hash(methods),manifestSha256:hash(manifestBytes),sourceIdentity:manifest.sourceIdentity.sha256};
 http=await startHttpFixture(script);
 browser=await chromium.launch({...pinnedChromiumUse.launchOptions,headless:true});await qualifyBrowser(browser,output);
 for(let repeat=0;repeat<3;repeat++)for(const config of MATRIX_CASES)await runCase(config,repeat,'matrix',http.origin,http.records);
 for(const config of HARD_CASES)await runCase(config,config.repeat,'burst-cancel',http.origin,http.records);
 await browser.close();browser=null;
 proxy=await startBoundaryProxy(script);
 browser=await chromium.launch({...pinnedChromiumUse.launchOptions,headless:true,proxy:proxy.proxy,args:['--ignore-certificate-errors-spki-list='+proxy.certificateSpki]});
 await qualifyBrowser(browser,join(output,'h2-proxy'));
 for(let repeat=0;repeat<6;repeat++)await runCase({name:'h2-small-length',error:'transport',cap:4096,protocol:'h2',wire:repeat<3?'open':'complete'},repeat,'h2-framing',http.origin,proxy.records);
 const matrix=report.results.filter(item=>item.suite==='matrix'),hard=report.results.filter(item=>item.suite!=='matrix');
 report.summary={matrix:{required:60,executed:matrix.length,passed:matrix.filter(item=>item.passed).length},hardNegative:{required:36,executed:hard.length,passed:hard.filter(item=>item.passed).length}};
 report.passed=matrix.length===60&&hard.length===36&&report.results.every(item=>item.passed);
}catch(error){report.error=String(error?.stack??error).slice(0,4096);}
finally{
 if(browser)await browser.close();if(proxy)await proxy.close();if(http)await http.close();
 await writeFile(join(output,'results.json'),JSON.stringify(report,null,2)+'\n');
 if(!report.passed)process.exitCode=1;
 console.log(JSON.stringify({scope:report.scope,passed:report.passed,summary:report.summary,error:report.error}));
}
