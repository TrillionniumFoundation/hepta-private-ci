// Real Rust UI + real gateway NotAttached path. This does not create a production host.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {readScreenshotText,screenshotConversationTabs,screenshotWordCenter} from '../tools/verify-robrix-pixels.mjs';
for(const width of [1280,640])test(`actual missing-owner status ${width}`,async({page},testInfo)=>{
 const sourceSha=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
 const faults=[],responses=[],requests=[],errors=[];const pendingFonts=new Set();
 const font=request=>/\.(?:ttf|otf)(?:[?#]|$)/i.test(request.url());
 page.on('request',request=>{if(font(request))pendingFonts.add(request);});
 page.on('requestfinished',request=>pendingFonts.delete(request));
 page.on('requestfailed',request=>{pendingFonts.delete(request);if(font(request))faults.push('font request failed');});
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
 const text=await readScreenshotText(screenshot,{language:'eng'});
 expect(text).toMatch(/not attached/i);expect(text).toMatch(/not current write authority/i);expect(text).toMatch(/runtime unavailable\s*\(Transport\)/i);
 expect(requests.map(item=>({method:item.method,path:new URL(item.url).pathname}))).toEqual([
  {method:'GET',path:'/api/hepta/owner-status'},{method:'GET',path:'/api/hepta/runtime'},
 ]);
 // An expected 503 is preserved as a transport observation; unrelated console
 // exceptions, missing assets, Rust panics and cross-origin faults still fail.
 const expectedHttpErrors=errors.filter(error=>error.url===legacyReply.url()&&/Failed to load resource.*503/.test(error.text));
 expect(errors.filter(error=>!expectedHttpErrors.includes(error))).toEqual([]);expect(faults).toEqual([]);
 const bytes=await readFile(screenshot);
 await writeFile(testInfo.outputPath('receipt.json'),JSON.stringify({sourceSha,width,ownerAttached:false,legacyRuntimeAvailable:false,requests,responses,expectedHttpErrors,faults,png:{name:'owner-not-attached.png',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')},ocr:text},null,2)+'\n');
});
