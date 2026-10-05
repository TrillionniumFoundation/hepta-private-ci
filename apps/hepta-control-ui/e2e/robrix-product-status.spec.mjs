// Real Rust UI + real gateway NotAttached path. This does not create a production host.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {robrixSourceIdentity} from '../tools/robrix-source-identity.mjs';
import {createHash} from 'node:crypto';
import {readProductStatusPixels} from '../tools/product-status-pixels.mjs';
import {auditProductConsole} from '../tools/product-console-audit.mjs';
import {execFileSync} from 'node:child_process';
import {readScreenshotText,screenshotConversationTabs,screenshotWordCenter} from '../tools/verify-robrix-pixels.mjs';
for(const width of [1280,640])for(const scenario of ['timeout','navigation','background'])test(`actual missing-owner status ${width} ${scenario}`,async({page,baseURL},testInfo)=>{
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
 const binding={sourceSha,sourceTree:gateway.sourceTree,uiSourceIdentity:manifest.sourceIdentity.sha256,uiManifestSha256:hash(manifestBytes),gateway};
 await writeFile(testInfo.outputPath('binding.json'),JSON.stringify(binding,null,2)+'\n');
 await writeFile(testInfo.outputPath('ui-build-manifest.json'),manifestBytes);
 const faults=[],responses=[],requests=[],errors=[],faultCases=[],networkFailures=[],finishedResponses=[];const pendingFonts=new Set();
 const ownerUrl=new URL('/api/hepta/owner-status',baseURL).href,runtimeUrl=new URL('/api/hepta/runtime',baseURL).href,sdkUrl=new URL('/makepad_platform/web.js',baseURL).href;
 let phase='initial',nextRequestId=0;const requestRecords=new Map(),proofs={},cancellations=[];
 function requestRecord(request){
  if(!requestRecords.has(request)){const record={id:++nextRequestId,url:request.url(),method:request.method(),phase};requestRecords.set(request,record);requests.push(record);}
  return requestRecords.get(request);
 }
 function rawAudit(){return {binding,scenario,errors,requests,responses,failures:networkFailures,cancellations,proofs,sdkUrl,runtimeUrl,ownerUrl,faults};}
 async function audit(name){
  await Promise.all(finishedResponses);
  const raw=rawAudit();await writeFile(testInfo.outputPath(name+'-raw.json'),JSON.stringify(raw,null,2)+'\n');
  const result=auditProductConsole(raw);await writeFile(testInfo.outputPath(name+'.json'),JSON.stringify(result,null,2)+'\n');
  expect(result.passed).toBe(true);expect(faults).toEqual([]);return result;
 }
 const font=request=>/\.(?:ttf|otf)(?:[?#]|$)/i.test(request.url());
 page.on('request',request=>{if(font(request))pendingFonts.add(request);});
 page.on('requestfinished',request=>pendingFonts.delete(request));
 page.on('requestfailed',request=>{pendingFonts.delete(request);if(font(request))faults.push({kind:'font request failed',url:request.url(),error:request.failure()?.errorText});if(new URL(request.url()).pathname.startsWith('/api/hepta/'))networkFailures.push({...requestRecord(request),error:request.failure()?.errorText});});
 page.on('pageerror',error=>faults.push(error.message));
 page.on('console',message=>{if(message.type()==='error')errors.push({text:message.text(),url:message.location().url,phase});});
 page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/hepta/'))requestRecord(request);});
 page.on('response',response=>{if(new URL(response.url()).pathname.startsWith('/api/hepta/')){
  const record={...requestRecord(response.request()),status:response.status(),finished:false};responses.push(record);
  finishedResponses.push(response.finished().then(error=>{record.finished=error===null;record.finishError=error?String(error):null;},error=>{record.finishError=String(error);}));
 }});
 try {
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
 const pendingReleases=new Set();
 async function holdOwner(name){
  let release,entered,rejectReady,finished,requestId=null;const gate=new Promise(resolve=>{release=resolve;});
  const ready=new Promise((resolve,reject)=>{entered=resolve;rejectReady=reject;});const done=new Promise(resolve=>{finished=resolve;});
  const record={name,mode:'hold actual gateway response bytes',lateFulfillReturned:false};pendingReleases.add(release);
  const handler=async route=>{
   try{
    if(requestId!==null)throw new Error('More than one held owner request in a fresh-page case');
    requestId=requestRecord(route.request()).id;record.requestId=requestId;
    const response=await route.fetch({timeout:5000});expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({schema:'hepta.owner-lease-observation.v1',observation:{status:'not_attached'}});
    entered();await gate;
    try{await route.fulfill({response});record.lateFulfillReturned=true;}
    catch(error){record.lateFulfillError=String(error).slice(0,500);}
   }catch(error){rejectReady(error);try{await route.abort();}catch{}}
   finally{pendingReleases.delete(release);finished();}
  };
  await page.route('**/api/hepta/owner-status',handler);
  return {ready,get requestId(){return requestId;},async finish(){release();await done;await page.unroute('**/api/hepta/owner-status',handler);faultCases.push(record);}};
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
  const timeoutReply=await timeoutLegacy;expect(timeoutReply.status()).toBe(503);expect(await timeoutReply.finished()).toBeNull();await timeoutSdk503;
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
 await held.finish();expect(ownerCount()).toBe(beforeCancellation+1);
 const late=await observedText('late-after-'+scenario,expectedState);expect(late.passed).toBe(true);
 await expect.poll(()=>networkFailures.filter(f=>f.id===held.requestId).length).toBe(1);
 cancellations.push({requestId:held.requestId,phase:scenario});
 proofs[scenario]={ownerState:expectedState,ownerVerified:late.passed,transportVerified:/runtime unavailable\s*\(Transport\)/i.test(late.text)};
 }finally{for(const release of pendingReleases)release();await page.unrouteAll({behavior:'ignoreErrors'});}
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
 }finally{await writeFile(testInfo.outputPath('raw-request-audit.json'),JSON.stringify(rawAudit(),null,2)+'\n');}
});
