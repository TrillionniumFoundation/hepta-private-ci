// Real Rust UI + real gateway NotAttached path. This does not create a production host.
import {test,expect} from '@playwright/test';
import {observeFontDelivery} from '../tools/font-delivery-diagnostic.mjs';
import {recordDiagnosticBrowser} from '../tools/font-diagnostic-browser-identity.mjs';
import {readFile,writeFile} from 'node:fs/promises';
import {robrixSourceIdentity} from '../tools/robrix-source-identity.mjs';
import {createHash} from 'node:crypto';
import {readProductStatusPixels} from '../tools/product-status-pixels.mjs';
import {auditProductConsole} from '../tools/product-console-audit.mjs';
import {holdOwnerResponse} from '../tools/hold-owner-response.mjs';
import {execFileSync} from 'node:child_process';
import {readScreenshotText,screenshotConversationTabs,screenshotWordCenter} from '../tools/verify-robrix-pixels.mjs';
for(const width of [1280,640])for(const scenario of ['timeout','navigation','background'])test(`actual missing-owner status ${width} ${scenario}`,async({page,baseURL,browser},testInfo)=>{
 await recordDiagnosticBrowser(browser,testInfo);
 let sdkDelivery;
 const sourceSha=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
 expect(execFileSync('git',['status','--porcelain','--untracked-files=normal'],{encoding:'utf8'}).trim()).toBe('');
 const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
 const manifestBytes=await readFile('dist/build-manifest.json');const manifest=JSON.parse(manifestBytes);
 expect(manifest.sourceIdentity.sha256).toBe((await robrixSourceIdentity(process.cwd())).sha256);
 const binary=process.env.HEPTA_GATEWAY_EXAMPLE;expect(binary).toBeTruthy();
 const gateway=JSON.parse(await readFile(binary+'.hepta-build.json','utf8'));
 expect(gateway.sourceCommit).toBe(sourceSha);
 expect(gateway.sourceTree).toBe(execFileSync('git',['rev-parse','HEAD^{tree}'],{encoding:'utf8'}).trim());
 expect(hash(await readFile(binary))).toBe(gateway.binarySha256);
 const binding={sourceSha,sourceTree:gateway.sourceTree,uiSourceIdentity:manifest.sourceIdentity.sha256,uiManifestSha256:hash(manifestBytes),gateway,...(testInfo.project.metadata.diagnosticOnly?{diagnosticOnly:true,project:testInfo.project.name}:{})};
 await writeFile(testInfo.outputPath('binding.json'),JSON.stringify(binding,null,2)+'\n');
 await writeFile(testInfo.outputPath('ui-build-manifest.json'),manifestBytes);
 const faults=[],responses=[],requests=[],errors=[],faultCases=[],networkFailures=[],finishedResponses=[];const pendingFonts=new Set();
 // Diagnostic observers only: do not consume bodies, cancel requests, alter cache,
 // replace SDK APIs, or waive any existing font/console/lifecycle assertion.
 const diagnosticStart=performance.now(),fontRequests=[],fontEvents=[],fontResponseFinished=[],consoleEvents=[],cdpFontEvents=[],diagnosticWaits=[];
 const apiNetworkEvents=[],apiWaits=[];
 let diagnosticComplete=false,diagnosticFailed=false;
 const diagnosticOverflow={fontRequests:0,fontEvents:0,consoleEvents:0,cdpFontEvents:0,apiNetworkEvents:0,apiWaits:0};
 const diagnosticMs=()=>Math.round((performance.now()-diagnosticStart)*1000)/1000;
 const appendDiagnostic=(name,values,value)=>{if(diagnosticComplete)return;if(values.length<512)values.push(value);else diagnosticOverflow[name]++;};
 const diagnosticPath=value=>{try{return new URL(value,baseURL).pathname.slice(0,512);}catch{return 'unavailable';}};
 const diagnosticError=value=>String(value).match(/net::[A-Z_]+|ERR_[A-Z_]+/)?.[0]??(value===null?null:'unclassified-error');
 const diagnosticFrame=frame=>({functionName:frame.functionName.slice(0,120),path:diagnosticPath(frame.url),lineNumber:frame.lineNumber,columnNumber:frame.columnNumber});
 async function settleFontObservations(scope){
  let timer;const observedCount=fontResponseFinished.length;
  try{
   const completed=await Promise.race([Promise.allSettled(fontResponseFinished).then(()=>true),new Promise(resolve=>{timer=setTimeout(()=>resolve(false),2000);})]);
   const settled=completed&&observedCount===fontResponseFinished.length;
   if(diagnosticWaits.length<4)diagnosticWaits.push({scope,settled,observedCount,observations:fontResponseFinished.length,ms:diagnosticMs()});
   return settled;
  }finally{clearTimeout(timer);}
 }
 const fontRequestIds=new Map(),cdpFontIds=new Set(),cdpApiIds=new Set();let cdp=null,browserLifecycle=null;
 function fontRecord(request){
  if(!fontRequestIds.has(request)){
   if(diagnosticComplete||fontRequestIds.size>=512){diagnosticOverflow.fontRequests++;return null;}
   const id=fontRequestIds.size+1;let frameUrl;
   try{frameUrl=diagnosticPath(request.frame().url());}catch{frameUrl='unavailable';}
   const redirectedFrom=request.redirectedFrom();
   fontRequestIds.set(request,id);
   appendDiagnostic('fontRequests',fontRequests,{id,path:diagnosticPath(request.url()),method:request.method(),resourceType:request.resourceType(),isNavigationRequest:request.isNavigationRequest(),frameUrl,redirectedFrom:redirectedFrom?diagnosticPath(redirectedFrom.url()):null,phase,ms:diagnosticMs()});
  }
  return fontRequestIds.get(request);
 }
 function fontEvent(request,event,details={}){
  if(diagnosticComplete)return;
  const id=fontRecord(request);if(id===null)return;
  appendDiagnostic('fontEvents',fontEvents,{id,event,phase,ms:diagnosticMs(),...details});
 }
 function cdpFontEvent(event,details){appendDiagnostic('cdpFontEvents',cdpFontEvents,{event,phase,ms:diagnosticMs(),...details});}
 function cdpApiEvent(event,details){appendDiagnostic('apiNetworkEvents',apiNetworkEvents,{event,phase,ms:diagnosticMs(),...details});}
 function apiWait(name,state){appendDiagnostic('apiWaits',apiWaits,{name,state,phase,ms:diagnosticMs()});}
 async function observeFontInitiators(){
  // The product config is Chromium-only. CDP is passive observation here: no
  // Fetch domain, request interception, cache overrides or response body reads.
  cdp=await page.context().newCDPSession(page);
  cdp.on('Network.requestWillBeSent',event=>{
   if(!diagnosticComplete&&(event.request.url===ownerUrl||event.request.url===runtimeUrl)){
    if(cdpApiIds.has(event.requestId)||cdpApiIds.size<128){
     cdpApiIds.add(event.requestId);
     cdpApiEvent('requestWillBeSent',{requestId:event.requestId,path:diagnosticPath(event.request.url),method:event.request.method,type:event.type,timestamp:event.timestamp});
    }else diagnosticOverflow.apiNetworkEvents++;
   }
   if(!/\.(?:ttf|otf)(?:[?#]|$)/i.test(event.request.url))return;
   if(diagnosticComplete)return;
   if(!cdpFontIds.has(event.requestId)&&cdpFontIds.size>=512){diagnosticOverflow.cdpFontEvents++;return;}
   cdpFontIds.add(event.requestId);
   const initiator=event.initiator;
   cdpFontEvent('requestWillBeSent',{requestId:event.requestId,path:diagnosticPath(event.request.url),method:event.request.method,type:event.type,loaderId:event.loaderId,frameId:event.frameId,documentPath:diagnosticPath(event.documentURL),timestamp:event.timestamp,initiator:{type:initiator.type,path:initiator.url?diagnosticPath(initiator.url):null,lineNumber:initiator.lineNumber,columnNumber:initiator.columnNumber,callFrames:initiator.stack?.callFrames?.slice(0,12).map(diagnosticFrame),parentCallFrames:initiator.stack?.parent?.callFrames?.slice(0,12).map(diagnosticFrame)}});
  });
  cdp.on('Network.responseReceived',event=>{
   if(cdpApiIds.has(event.requestId)){
    const response=event.response;
    const header=name=>String(Object.entries(response.headers).find(([key])=>key.toLowerCase()===name)?.[1]??'').slice(0,256);
    cdpApiEvent('responseReceived',{requestId:event.requestId,path:diagnosticPath(response.url),timestamp:event.timestamp,status:response.status,protocol:response.protocol,mimeType:response.mimeType,fromDiskCache:response.fromDiskCache,fromServiceWorker:response.fromServiceWorker,headers:{contentLength:header('content-length'),transferEncoding:header('transfer-encoding'),contentEncoding:header('content-encoding'),cacheControl:header('cache-control')}});
   }
   if(!cdpFontIds.has(event.requestId))return;
   const response=event.response;
   cdpFontEvent('responseReceived',{requestId:event.requestId,timestamp:event.timestamp,type:event.type,path:diagnosticPath(response.url),status:response.status,mimeType:response.mimeType,protocol:response.protocol,fromDiskCache:response.fromDiskCache,fromServiceWorker:response.fromServiceWorker,encodedDataLength:response.encodedDataLength,timing:response.timing});
  });
  cdp.on('Network.dataReceived',event=>{if(cdpApiIds.has(event.requestId))cdpApiEvent('dataReceived',{requestId:event.requestId,timestamp:event.timestamp,dataLength:event.dataLength,encodedDataLength:event.encodedDataLength});});
  cdp.on('Network.loadingFinished',event=>{
   if(cdpApiIds.has(event.requestId))cdpApiEvent('loadingFinished',{requestId:event.requestId,timestamp:event.timestamp,encodedDataLength:event.encodedDataLength});
   if(cdpFontIds.has(event.requestId))cdpFontEvent('loadingFinished',{requestId:event.requestId,timestamp:event.timestamp,encodedDataLength:event.encodedDataLength});
  });
  cdp.on('Network.loadingFailed',event=>{
   if(cdpApiIds.has(event.requestId))cdpApiEvent('loadingFailed',{requestId:event.requestId,timestamp:event.timestamp,type:event.type,errorText:diagnosticError(event.errorText),canceled:event.canceled,blockedReason:event.blockedReason});
   if(cdpFontIds.has(event.requestId))cdpFontEvent('loadingFailed',{requestId:event.requestId,timestamp:event.timestamp,type:event.type,errorText:diagnosticError(event.errorText),canceled:event.canceled,blockedReason:event.blockedReason,corsError:event.corsErrorStatus?.corsError});
  });
  await cdp.send('Network.enable');
  await page.addInitScript(()=>{
   window.__heptaProductLifecycle=[];window.__heptaProductLifecycleOverflow=0;
   const record=event=>{
    if(window.__heptaProductLifecycle.length>=128){window.__heptaProductLifecycleOverflow++;return;}
    window.__heptaProductLifecycle.push({type:event.type,ms:performance.now(),visibility:document.visibilityState,persisted:event.persisted??null,target:event.target?.nodeName??null});
   };
   for(const type of ['pagehide','pageshow','beforeunload'])window.addEventListener(type,record,{capture:true});
   for(const type of ['visibilitychange','webglcontextlost','webglcontextrestored'])document.addEventListener(type,record,{capture:true});
  });
 }
 const ownerUrl=new URL('/api/hepta/owner-status',baseURL).href,runtimeUrl=new URL('/api/hepta/runtime',baseURL).href,sdkUrl=new URL('/makepad_platform/web.js',baseURL).href;
 let phase='initial',nextRequestId=0;const requestRecords=new Map(),proofs={},cancellations=[];
 function requestRecord(request){
  if(!requestRecords.has(request)){const record={id:++nextRequestId,url:request.url(),method:request.method(),phase};requestRecords.set(request,record);requests.push(record);}
  return requestRecords.get(request);
 }
 function rawAudit(){return {binding,scenario,errors,requests,responses,failures:networkFailures,cancellations,proofs,sdkUrl,runtimeUrl,ownerUrl,faults,apiDiagnostics:{network:apiNetworkEvents,waits:apiWaits},fontDiagnostics:{fontRequests,fontEvents,cdpFontEvents,consoleEvents,browserLifecycle,diagnosticOverflow,diagnosticWaits}};}
 async function audit(name){
  await Promise.all(finishedResponses);
  await settleFontObservations(name);
  const raw=rawAudit();await writeFile(testInfo.outputPath(name+'-raw.json'),JSON.stringify(raw,null,2)+'\n');
  const result=auditProductConsole(raw);await writeFile(testInfo.outputPath(name+'.json'),JSON.stringify(result,null,2)+'\n');
  expect(result.passed).toBe(true);expect(faults).toEqual([]);return result;
 }
 const font=request=>/\.(?:ttf|otf)(?:[?#]|$)/i.test(request.url());
 page.on('request',request=>{if(font(request)){pendingFonts.add(request);fontEvent(request,'request');}});
 page.on('requestfinished',request=>{pendingFonts.delete(request);if(font(request))fontEvent(request,'requestfinished');});
 page.on('requestfailed',request=>{pendingFonts.delete(request);if(font(request)){fontEvent(request,'requestfailed',{error:diagnosticError(request.failure()?.errorText)});faults.push({kind:'font request failed',url:request.url(),error:request.failure()?.errorText});}if(new URL(request.url()).pathname.startsWith('/api/hepta/'))networkFailures.push({...requestRecord(request),error:request.failure()?.errorText});});
 page.on('pageerror',error=>faults.push(error.message));
 page.on('console',message=>{const text=message.text(),location=message.location();const kind=/webgl.*context.*lost|context.*lost/i.test(text)?'context-lost':/context.*(?:restore|restoring|restoration)/i.test(text)?'context-restored':/\[makepad\]\[http\]\[err\]/.test(text)?'sdk-http-error':/\[makepad\]\[http\]\[fail\]/.test(text)?'sdk-http-status-failure':'other';appendDiagnostic('consoleEvents',consoleEvents,{type:message.type(),kind,path:diagnosticPath(location.url),lineNumber:location.lineNumber,columnNumber:location.columnNumber,characters:text.length,phase,ms:diagnosticMs()});if(message.type()==='error')errors.push({text:message.text(),url:message.location().url,phase});});
 page.on('response',response=>{
  const request=response.request();if(!font(request)||diagnosticComplete)return;
  if(fontResponseFinished.length>=512){diagnosticOverflow.fontEvents++;return;}
  fontEvent(request,'response',{status:response.status()});
  fontResponseFinished.push(response.finished().then(async error=>{
   fontEvent(request,'response.finished',{error:diagnosticError(error)});
   if(error===null&&!diagnosticComplete){
    try{const sizes=await request.sizes();fontEvent(request,'response.sizes',{responseBodySize:sizes.responseBodySize});}
    catch(error){fontEvent(request,'response.sizes unavailable',{error:diagnosticError(error)});}
   }
  },error=>fontEvent(request,'response.finished rejected',{error:diagnosticError(error)})));
 });
 page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/hepta/'))requestRecord(request);});
 page.on('response',response=>{if(new URL(response.url()).pathname.startsWith('/api/hepta/')){
  const record={...requestRecord(response.request()),status:response.status(),finished:false};responses.push(record);
  finishedResponses.push(response.finished().then(error=>{record.finished=error===null;record.finishError=error?String(error):null;},error=>{record.finishError=String(error);}));
 }});
 try {
 if(testInfo.project.metadata.fontDeliveryObserver)sdkDelivery=await observeFontDelivery(page,manifest);
 await observeFontInitiators();
 await page.setViewportSize({width,height:800});await page.goto('/');
 await expect(page.locator('canvas')).toBeVisible();await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});
 const settle=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);await settle();
 const initial=testInfo.outputPath('chat.png');await page.screenshot({path:initial,caret:'initial'});
 const tabs=await screenshotConversationTabs(initial,page.viewportSize(),{recordOcr:true});
 await page.mouse.click(tabs.Console.x,tabs.Console.y);await settle();
 const before=testInfo.outputPath('before-read.png');await page.screenshot({path:before,caret:'initial'});
 expect(requests).toEqual([]);
 const refresh=await screenshotWordCenter(before,'Refresh',width,{recordOcr:true});
 const initialSdk503=page.waitForEvent('console',message=>message.type()==='error'&&message.location().url===sdkUrl&&message.text()===`[makepad][http][fail] 503 ${runtimeUrl}`);
 const owner=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/hepta/owner-status');
 const legacy=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/hepta/runtime');
 await page.mouse.click(refresh.x,refresh.y);
 const [ownerReply,legacyReply]=await Promise.all([owner,legacy]);
 expect(ownerReply.status()).toBe(200);expect(await ownerReply.json()).toEqual({schema:'hepta.owner-lease-observation.v1',observation:{status:'not_attached'}});
 expect(legacyReply.status()).toBe(503);
 await settle();
 const screenshot=testInfo.outputPath('owner-not-attached.png');await page.screenshot({path:screenshot,caret:'initial'});
 const observation=await readProductStatusPixels(screenshot,'notAttached');
 await writeFile(testInfo.outputPath('owner-not-attached-ocr.json'),JSON.stringify(observation,null,2)+'\n');
 expect(observation.passed).toBe(true);const text=observation.text;
 expect(requests.map(item=>({method:item.method,path:new URL(item.url).pathname}))).toEqual([
  {method:'GET',path:'/api/hepta/owner-status'},{method:'GET',path:'/api/hepta/runtime'},
 ]);
 await legacyReply.finished();await initialSdk503;
 proofs.initial={ownerState:'notAttached',ownerVerified:observation.passed,transportVerified:/runtime unavailable\s*\(Transport\)/i.test(text)};
 if(sdkDelivery)await sdkDelivery.check();
 await audit('initial-read-audit');
 phase=scenario;

 const ownerCount=()=>requests.filter(item=>new URL(item.url).pathname==='/api/hepta/owner-status').length;
 async function observedText(name,state){
  await settle();const path=testInfo.outputPath(name+'.png');await page.screenshot({path,caret:'initial'});
  if(!state)return {path,text:await readScreenshotText(path,{language:'eng'})};
  const observation=await readProductStatusPixels(path,state);
  await writeFile(testInfo.outputPath(name+'-ocr.json'),JSON.stringify(observation,null,2)+'\n');
  return {path,...observation};
 }
 const pendingHolds=new Set();
 async function holdOwner(name){
  const held=await holdOwnerResponse(page,ownerUrl,request=>requestRecord(request).id,name);
  pendingHolds.add(held);
  return {ready:held.ready,get requestId(){return held.requestId;},async finish(){const record=await held.finish();pendingHolds.delete(held);faultCases.push(record);}};
 }
 // Hold a real response, then exercise the actual Rust five-second timeout and
 // disabled/single-flight control. No fabricated success body is injected.
 try {
 const timeoutLegacy=scenario==='timeout'?page.waitForResponse(response=>response.url()===runtimeUrl&&requestRecord(response.request()).phase==='timeout'):null;
 const timeoutSdk503=scenario==='timeout'?page.waitForEvent('console',message=>phase==='timeout'&&message.type()==='error'&&message.location().url===sdkUrl&&message.text()===`[makepad][http][fail] 503 ${runtimeUrl}`):null;
 const held=await holdOwner(scenario);const beforeCancellation=ownerCount();
 await page.mouse.click(refresh.x,refresh.y);await held.ready;
 let expectedState;
 if(scenario==='timeout'){
  for(let index=0;index<3;index++)await page.mouse.click(refresh.x,refresh.y);
  await settle();expect(ownerCount()).toBe(beforeCancellation+1);
  await expect.poll(async()=> (await observedText('timed-out','timedOut')).passed,{timeout:15000,intervals:[250]}).toBe(true);
  const timeoutReply=await timeoutLegacy;expect(timeoutReply.status()).toBe(503);
  apiWait('timeout-runtime.finished','start');
  await expect.poll(
   () => apiNetworkEvents.some(event => event.path === '/api/hepta/runtime' && event.phase === 'timeout' && (event.event === 'loadingFinished' || event.event === 'loadingFailed')),
   {timeout:5000,intervals:[100]}
  ).toBe(true);
  apiWait('timeout-runtime.finished','done');await timeoutSdk503;
  expectedState='timedOut';
 }else if(scenario==='navigation'){
  const currentTabs=await screenshotConversationTabs((await observedText('reading')).path,page.viewportSize(),{recordOcr:true});
  await page.mouse.click(currentTabs.Chat.x,currentTabs.Chat.y);await settle();
  const chatTabs=await screenshotConversationTabs((await observedText('chat-after-cancel')).path,page.viewportSize(),{recordOcr:true});
  await page.mouse.click(chatTabs.Console.x,chatTabs.Console.y);await settle();
  expectedState='noObservation';
 }else{
  // Synthetic pinned-SDK lifecycle routing, not physical OS background proof.
  await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true})));
  await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
  expectedState='noObservation';
 }
 apiWait('held-owner.finish','start');await held.finish();apiWait('held-owner.finish','done');expect(ownerCount()).toBe(beforeCancellation+1);
 const late=await observedText('late-after-'+scenario,expectedState);expect(late.passed).toBe(true);
 await expect.poll(()=>networkFailures.filter(f=>f.id===held.requestId).length).toBe(1);
 cancellations.push({requestId:held.requestId,phase:scenario});
 proofs[scenario]={ownerState:expectedState,ownerVerified:late.passed,transportVerified:/runtime unavailable\s*\(Transport\)/i.test(late.text)};
 }finally{await Promise.allSettled([...pendingHolds].map(held=>held.finish()));}
 await Promise.all(finishedResponses);
 expect(requests.map(item=>({method:item.method,path:new URL(item.url).pathname,phase:item.phase}))).toEqual([
  {method:'GET',path:'/api/hepta/owner-status',phase:'initial'},
  {method:'GET',path:'/api/hepta/runtime',phase:'initial'},
  {method:'GET',path:'/api/hepta/owner-status',phase:scenario},
  ...(scenario==='timeout'?[{method:'GET',path:'/api/hepta/runtime',phase:'timeout'}]:[]),
 ]);
 const errorAudit=await audit('final-read-audit');
 const bytes=await readFile(screenshot);
 await writeFile(testInfo.outputPath('receipt.json'),JSON.stringify({...binding,width,ownerAttached:false,legacyRuntimeAvailable:false,requests,responses,errorAudit,faults,faultCases,networkFailures,scenario,proofs,cancellations,physicalBackgroundQualified:false,png:{name:'owner-not-attached.png',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')},ocr:text},null,2)+'\n');
 }catch(error){diagnosticFailed=true;throw error;}finally{
  // Preserve diagnostics even when initial-read-audit fails. Never wait without
  // bound for unfinished font responses during another failing test path.
  const fontCompletionSettled=await settleFontObservations('finally');
  diagnosticComplete=true;
  let lifecycleTimer;
  try{browserLifecycle=await Promise.race([
   page.evaluate(()=>({events:window.__heptaProductLifecycle??[],overflow:window.__heptaProductLifecycleOverflow??0,readyState:document.readyState,visibility:document.visibilityState,bootPhase:document.documentElement.dataset.heptaBootPhase??null,canvas:[...document.querySelectorAll('canvas')].map(canvas=>({width:canvas.width,height:canvas.height}))})).catch(()=>({observationError:'page-unavailable'})),
   new Promise(resolve=>{lifecycleTimer=setTimeout(()=>resolve({observationError:'observation-deadline'}),1000);})
  ]);}finally{clearTimeout(lifecycleTimer);}
  browserLifecycle.fontCompletionSettled=fontCompletionSettled;
  const raw=rawAudit();
  try{await writeFile(testInfo.outputPath('raw-request-audit.json'),JSON.stringify(raw,null,2)+'\n');}
  finally{
   try{
    if(diagnosticFailed||faults.length){
     // Structured path-only records remain useful without parsing truncated JSON.
     const identity={sourceSha,sourceTree:binding.sourceTree,uiSourceIdentity:binding.uiSourceIdentity,uiManifestSha256:binding.uiManifestSha256,gatewayBinarySha256:gateway.binarySha256};
     console.log(JSON.stringify({scope:'strict font lifecycle diagnostic summary; not acceptance',identity,scenario,width,diagnosticWaits,diagnosticOverflow,fontRequestCount:fontRequests.length,truncatedFontRequests:Math.max(0,fontRequests.length-24),consoleEvents:consoleEvents.slice(0,32),truncatedConsoleEvents:Math.max(0,consoleEvents.length-32),lifecycle:{...browserLifecycle,events:browserLifecycle.events?.slice(0,16),truncatedEvents:Math.max(0,(browserLifecycle.events?.length??0)-16)}}));
     for(const request of fontRequests.slice(0,24)){
      const related=cdpFontEvents.filter(event=>event.event==='requestWillBeSent'&&event.path===request.path);
      const cdpRequests=related.slice(0,2).map(event=>({requestId:event.requestId,method:event.method,type:event.type,ms:event.ms,initiator:{...event.initiator,callFrames:event.initiator.callFrames?.slice(0,2),parentCallFrames:event.initiator.parentCallFrames?.slice(0,2)},events:cdpFontEvents.filter(item=>item.requestId===event.requestId&&item.event!=='requestWillBeSent').slice(0,4)}));
      const events=fontEvents.filter(event=>event.id===request.id);
      console.log(JSON.stringify({scope:'strict font request diagnostic; not acceptance',scenario,width,request,events:events.slice(0,8),truncatedEvents:Math.max(0,events.length-8),cdpRequests,truncatedCdpRequests:Math.max(0,related.length-2)}));
     }
    }
   }catch{console.log('strict font lifecycle diagnostics could not be serialized');}
   finally{try{if(sdkDelivery)await sdkDelivery.close(testInfo.outputPath('sdk-font-delivery.json'),{priorFailure:diagnosticFailed});}finally{if(cdp)await cdp.detach().catch(()=>{});}}
  }
 }
});
