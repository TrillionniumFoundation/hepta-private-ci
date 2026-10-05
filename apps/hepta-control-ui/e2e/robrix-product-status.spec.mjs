// Real Rust UI + real gateway NotAttached path. This does not create a production host.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {robrixSourceIdentity} from '../tools/robrix-source-identity.mjs';
import {createHash} from 'node:crypto';
import {readProductStatusPixels} from '../tools/product-status-pixels.mjs';
import {execFileSync} from 'node:child_process';
import {readScreenshotText,screenshotConversationTabs,screenshotWordCenter} from '../tools/verify-robrix-pixels.mjs';
for(const width of [1280,640])test(`actual missing-owner status ${width}`,async({page},testInfo)=>{
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
 const faults=[],responses=[],requests=[],errors=[],faultCases=[],networkFailures=[];const pendingFonts=new Set();
 const font=request=>/\.(?:ttf|otf)(?:[?#]|$)/i.test(request.url());
 page.on('request',request=>{if(font(request))pendingFonts.add(request);});
 page.on('requestfinished',request=>pendingFonts.delete(request));
 page.on('requestfailed',request=>{pendingFonts.delete(request);if(font(request))faults.push('font request failed');if(new URL(request.url()).pathname.startsWith('/api/hepta/'))networkFailures.push({url:request.url(),error:request.failure()?.errorText});});
 page.on('pageerror',error=>faults.push(error.message));
 page.on('console',message=>{if(message.type()==='error')errors.push({text:message.text(),url:message.location().url});});
 page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/hepta/'))requests.push({url:request.url(),method:request.method()});});
 page.on('response',response=>{if(new URL(response.url()).pathname.startsWith('/api/hepta/'))responses.push({url:response.url(),status:response.status()});});
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
  let release,entered,rejectReady,finished;const gate=new Promise(resolve=>{release=resolve;});
  const ready=new Promise((resolve,reject)=>{entered=resolve;rejectReady=reject;});const done=new Promise(resolve=>{finished=resolve;});
  const record={name,mode:'hold actual gateway response bytes',lateFulfillReturned:false};pendingReleases.add(release);
  const handler=async route=>{
   try{
    const response=await route.fetch({timeout:5000});expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({schema:'hepta.owner-lease-observation.v1',observation:{status:'not_attached'}});
    entered();await gate;
    try{await route.fulfill({response});record.lateFulfillReturned=true;}
    catch(error){record.lateFulfillError=String(error).slice(0,500);}
   }catch(error){rejectReady(error);try{await route.abort();}catch{}}
   finally{pendingReleases.delete(release);finished();}
  };
  await page.route('**/api/hepta/owner-status',handler);
  return {ready,async finish(){release();await done;await page.unroute('**/api/hepta/owner-status',handler);faultCases.push(record);}};
 }
 // Hold a real response, then exercise the actual Rust five-second timeout and
 // disabled/single-flight control. No fabricated success body is injected.
 try {
 const timeoutHold=await holdOwner('repeat-click-and-timeout');const beforeTimeout=ownerCount();
 await page.mouse.click(refresh.x,refresh.y);await timeoutHold.ready;
 for(let index=0;index<3;index++)await page.mouse.click(refresh.x,refresh.y);
 await settle();expect(ownerCount()).toBe(beforeTimeout+1);
 await expect.poll(async()=> (await observedText('timed-out','timedOut')).passed,{timeout:15000,intervals:[250]}).toBe(true);
 await timeoutHold.finish();
 expect((await observedText('late-after-timeout','timedOut')).passed).toBe(true);
 // Navigating away cancels the pending read; reopening does not start another
 // scan and an old reply cannot populate the new view.
 const navigationHold=await holdOwner('navigation-cancel');const beforeNavigation=ownerCount();
 await page.mouse.click(refresh.x,refresh.y);await navigationHold.ready;
 const currentTabs=await screenshotConversationTabs((await observedText('reading')).path,page.viewportSize(),{recordOcr:true});
 await page.mouse.click(currentTabs.Chat.x,currentTabs.Chat.y);await settle();
 const chatTabs=await screenshotConversationTabs((await observedText('chat-after-cancel')).path,page.viewportSize(),{recordOcr:true});
 await page.mouse.click(chatTabs.Console.x,chatTabs.Console.y);await settle();
 await navigationHold.finish();expect(ownerCount()).toBe(beforeNavigation+1);
 expect((await observedText('late-after-navigation','noObservation')).passed).toBe(true);
 // Deterministic browser-lifecycle injection through the pinned SDK listener.
 // This covers routing/cancellation, not a physical OS backgrounding claim.
 const backgroundHold=await holdOwner('synthetic-persisted-pagehide');const beforeBackground=ownerCount();
 await page.mouse.click(refresh.x,refresh.y);await backgroundHold.ready;
 await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true})));
 await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
 await backgroundHold.finish();expect(ownerCount()).toBe(beforeBackground+1);
 expect((await observedText('late-after-background','noObservation')).passed).toBe(true);
 }finally{for(const release of pendingReleases)release();await page.unrouteAll({behavior:'ignoreErrors'});}
 // An expected 503 is preserved as a transport observation; unrelated console
 // exceptions, missing assets, Rust panics and cross-origin faults still fail.
 const expectedHttpErrors=errors.filter(error=>error.url===legacyReply.url()&&/Failed to load resource.*503/.test(error.text));
 expect(errors.filter(error=>!expectedHttpErrors.includes(error))).toEqual([]);expect(faults).toEqual([]);
 const bytes=await readFile(screenshot);
 await writeFile(testInfo.outputPath('receipt.json'),JSON.stringify({...binding,width,ownerAttached:false,legacyRuntimeAvailable:false,requests,responses,expectedHttpErrors,faults,faultCases,networkFailures,physicalBackgroundQualified:false,png:{name:'owner-not-attached.png',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')},ocr:text},null,2)+'\n');
});
