// Real canvas evidence. OCR is a necessary glyph regression, not full visual/a11y acceptance.
import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {readScreenshotText,requireChatText,screenshotWordCenter} from '../tools/verify-robrix-pixels.mjs';
for(const viewport of [{width:1280,height:800},{width:640,height:800}]) {
 test(`Robrix host starts under strict CSP ${viewport.width}`,async({page,browserName},testInfo)=>{
  let phase='application';
  const errors=[];const logs=[];const uploads=[];const fonts=[];const pendingFonts=new Set();
  const isFont=request=>/\.(?:ttf|otf|woff2?)(?:[?#]|$)/i.test(request.url());
  page.on('pageerror',error=>errors.push({phase,message:error.message}));
  page.on('console',message=>{
   if(message.type()==='error') errors.push({phase,message:message.text()});
   if(logs.length<100) logs.push({phase,type:message.type(),text:message.text().slice(0,2000)});
  });
  page.on('request',request=>{
   if(/\/(?:api\/crash|\$report_error)/.test(request.url())) uploads.push(request.url());
   if(isFont(request)){pendingFonts.add(request);fonts.push({event:'request',url:request.url()});}
  });
  page.on('response',response=>{if(isFont(response.request())) fonts.push({event:'response',url:response.url(),status:response.status()});});
  page.on('requestfinished',request=>{if(isFont(request)){pendingFonts.delete(request);fonts.push({event:'finished',url:request.url()});}});
  page.on('requestfailed',request=>{if(isFont(request)){pendingFonts.delete(request);fonts.push({event:'failed',url:request.url(),error:request.failure()?.errorText});}});
  await page.addInitScript(()=>{
   window.__heptaTestPhase='application';window.__cspViolations=[];window.__snapshotStyles=[];window.__wasmStages=[];
   // Observe the real loader promises without choosing a different runtime path.
   for(const name of ['compileStreaming','compile','instantiate']){
    if(typeof WebAssembly[name]!=='function') continue;
    const original=WebAssembly[name].bind(WebAssembly);
    WebAssembly[name]=(...args)=>{
     window.__wasmStages.push({stage:name,event:'start',time:performance.now()});
     return original(...args).then(value=>{window.__wasmStages.push({stage:name,event:'complete',time:performance.now()});return value;},error=>{window.__wasmStages.push({stage:name,event:'failed',message:String(error),time:performance.now()});throw error;});
    };
   }
   if(typeof ReadableStreamDefaultReader!=='undefined'){
    const original=ReadableStreamDefaultReader.prototype.cancel;
    ReadableStreamDefaultReader.prototype.cancel=function(...args){
     window.__wasmStages.push({stage:'reader.cancel',event:'start',time:performance.now()});
     return original.apply(this,args).then(value=>{window.__wasmStages.push({stage:'reader.cancel',event:'complete',time:performance.now()});return value;},error=>{window.__wasmStages.push({stage:'reader.cancel',event:'failed',message:String(error),time:performance.now()});throw error;});
    };
   }
   document.addEventListener('securitypolicyviolation',event=>window.__cspViolations.push({phase:window.__heptaTestPhase,directive:event.violatedDirective,blockedURI:event.blockedURI}));
   new MutationObserver(records=>{for(const record of records) for(const node of record.addedNodes) if(node.nodeName==='STYLE') window.__snapshotStyles.push({phase:window.__heptaTestPhase,text:node.textContent});}).observe(document,{childList:true,subtree:true});
  });
  async function assertApplicationHealth(){
   expect(errors.filter(item=>item.phase==='application')).toEqual([]);
   expect(await page.evaluate(()=>window.__cspViolations.filter(item=>item.phase==='application'))).toEqual([]);
   expect(uploads).toEqual([]);
  }
  async function capture(name,{consoleView=false}={}){
   await assertApplicationHealth();
   phase='snapshot';await page.evaluate(()=>window.__heptaTestPhase='snapshot');
   const path=testInfo.outputPath(name+'.png');
   try {await page.screenshot({path,fullPage:true,caret:'initial'});}
   finally {await page.evaluate(()=>window.__heptaTestPhase='application');phase='application';}
   // Pinned Playwright1.63 WebKit/Firefox screenshot preparation injects exactly
   // an empty `body {}` style. Retain this blocked tool event; never waive app CSP.
   const snapshot=await page.evaluate(()=>({violations:window.__cspViolations.filter(item=>item.phase==='snapshot'),styles:window.__snapshotStyles.filter(item=>item.phase==='snapshot')}));
   const captureErrors=errors.filter(item=>item.phase==='snapshot');
   if(snapshot.violations.length||captureErrors.length){
    expect(['webkit','firefox']).toContain(browserName);
    expect(snapshot.styles.length).toBeGreaterThan(0);
    expect(snapshot.styles.every(item=>item.text==='body {}')).toBe(true);
    expect(snapshot.violations.every(item=>item.directive==='style-src-elem'&&item.blockedURI==='inline')).toBe(true);
    expect(snapshot.violations.length).toBeLessThanOrEqual(snapshot.styles.length*2);
    expect(captureErrors.every(item=>/Refused to apply a stylesheet/.test(item.message))).toBe(true);
    expect(captureErrors.length).toBeLessThanOrEqual(snapshot.styles.length*2);
   }
   const text=await readScreenshotText(path);
   await writeFile(testInfo.outputPath(name+'-ocr.txt'),text);
   if(consoleView){
    expect(text).toMatch(/Console/i);
    expect(text).toMatch(/composed|composition/i);
   }else {
    requireChatText(text,{fixtures:process.env.HEPTA_ROBRIX_FIXTURES==='1'});
    if(process.env.HEPTA_ROBRIX_FIXTURES==='1'){
     const ordinals=[...text.matchAll(/Fixture\s*(\d{1,3})\b/gi)].map(match=>Number(match[1]));
     expect(ordinals.length,'At least two real fixture messages must be visible').toBeGreaterThanOrEqual(2);
     expect(ordinals,'Rendered owner order must remain oldest to newest').toEqual([...ordinals].sort((a,b)=>a-b));
    }
   }
   await assertApplicationHealth();
   return {path,text};
  }
  async function clickRenderedWord(captured,word,options){
   const point=await screenshotWordCenter(captured.path,word,page.viewportSize().width,options);
   await page.mouse.click(point.x,point.y);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  }
  try {
   await page.setViewportSize(viewport);await page.goto('/');
   await expect(page.locator('canvas')).toBeVisible();
   await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});
   await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);
   await page.waitForTimeout(1000);
   expect(await page.locator('canvas').evaluate(canvas=>canvas.width>0&&canvas.height>0)).toBe(true);
   expect(await page.locator('meta[name=viewport]').getAttribute('content')).not.toContain('user-scalable=no');
   let captured;
   for(const theme of ['Aurora','Obsidian','Lunar']){
    await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);
    captured=await capture(`robrix-${theme}-${page.viewportSize().width}`);
    expect(captured.text.toLowerCase()).toContain(theme.toLowerCase());
    await page.setViewportSize({width:page.viewportSize().width===1280?640:1280,height:800});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    captured=await capture(`robrix-${theme}-after-resize`);
    if(theme==='Aurora'){
     await page.mouse.click(page.viewportSize().width*0.65,720);
     await page.keyboard.type('Theme round trip draft');
     captured=await capture('robrix-draft-before-theme');
     expect(captured.text).toMatch(/Theme round trip draft/i);
    }else{
     expect(captured.text).toMatch(/Theme round trip draft/i);
    }
    await clickRenderedWord(captured,theme);
    await page.keyboard.type(' kept');
   }
   captured=await capture('robrix-theme-round-trip');
   expect(captured.text).toMatch(/Aurora/i);
   expect(captured.text).toMatch(/Theme round trip draft/i);
   expect(captured.text).toMatch(/kept/i);
   await clickRenderedWord(captured,'Console',{topOnly:true});
   const consoleCapture=await capture('robrix-console',{consoleView:true});
   await clickRenderedWord(consoleCapture,page.viewportSize().width<760?'Chat':'Conversation',{topOnly:true});
   captured=await capture('robrix-console-round-trip');
   expect(captured.text).toMatch(/Theme round trip draft/i);

  } finally {
   const observed=await page.evaluate(()=>({violations:window.__cspViolations??[],snapshotStyles:window.__snapshotStyles??[],bootPhase:document.documentElement.dataset.heptaBootPhase??'unobserved',wasmStages:window.__wasmStages??[],readyState:document.readyState,canvas:[...document.querySelectorAll('canvas')].map(canvas=>({width:canvas.width,height:canvas.height})),resources:performance.getEntriesByType('resource').map(item=>({name:item.name,duration:item.duration,bytes:item.transferSize}))})).catch(()=>({}));
   const diagnostics=testInfo.outputPath('host-diagnostics.json');
   await writeFile(diagnostics,JSON.stringify({errors,logs,uploads,fonts,pendingFonts:[...pendingFonts].map(request=>request.url()),...observed},null,2));
   await testInfo.attach('host-diagnostics',{path:diagnostics,contentType:'application/json'});
  }
 });
}
