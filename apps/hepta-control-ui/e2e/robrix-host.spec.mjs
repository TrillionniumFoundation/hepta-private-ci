// Real canvas evidence. OCR is a necessary glyph regression, not full visual/a11y acceptance.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {captureSchedule} from '../tools/robrix-pixel-plan.mjs';
import {screenshotWordCenter,screenshotConversationTabs} from '../tools/verify-robrix-pixels.mjs';
for(const viewport of [{width:1280,height:800},{width:640,height:800}]) {
 test(`Robrix host starts under strict CSP ${viewport.width}`,async({page,browserName},testInfo)=>{
  let phase='application';
  const themeControlPoints=new Map();
  const sourceSha=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
  const fixtures=process.env.HEPTA_ROBRIX_FIXTURES==='1';
  const schedule=captureSchedule(viewport.width,fixtures);const pixelCaptures=[];const captureTimings=[];const controlTimings=[];
  const errors=[];const logs=[];const rustFontStates=[];const scrollObservations=[];const jumpObservations=[];const geometryObservations=[];const uploads=[];const fonts=[];const pendingFonts=new Set();
  const isFont=request=>/\.(?:ttf|otf|woff2?)(?:[?#]|$)/i.test(request.url());
  page.on('pageerror',error=>errors.push({phase,message:error.message}));
  page.on('console',message=>{
   if(message.type()==='error') errors.push({phase,message:message.text()});
   if(logs.length<500) logs.push({phase,type:message.type(),text:message.text().slice(0,2000)});
   const geometry=message.text().match(/HEPTA_FIXTURE_GEOMETRY frame=(\d+) (\{.*\})/);
   if(geometry){
    try{geometryObservations.push({frame:Number(geometry[1]),observedAt:performance.now(),phase,...JSON.parse(geometry[2])});if(geometryObservations.length>256)geometryObservations.shift();}
    catch(error){errors.push({phase,message:'Invalid real Rust geometry observation: '+String(error)});}
   }
   const scroll=message.text().match(/HEPTA_FIXTURE_SCROLL travel=([-\d.]+) at_end=(true|false) first=(\d+)/);
   if(scroll){scrollObservations.push({travel:Number(scroll[1]),atEnd:scroll[2]==='true',first:Number(scroll[3])});if(scrollObservations.length>64)scrollObservations.shift();}
   if(/HEPTA_FIXTURE_(?:SCROLL_ACTION|JUMP)/.test(message.text())){
    jumpObservations.push(message.text());if(jumpObservations.length>64)jumpObservations.shift();
   }
   if(rustFontStates.length<160&&/HEPTA_FIXTURE_(?:SHAPING|FONT_STATE|FONT_RESOURCE|RESOURCE_EVENT)/.test(message.text())) rustFontStates.push(message.text().slice(0,4000));
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
  async function assertApplicationHealth(assertion=expect){
   assertion(errors.filter(item=>item.phase==='application')).toEqual([]);
   assertion(await page.evaluate(()=>window.__cspViolations.filter(item=>item.phase==='application'))).toEqual([]);
   assertion(uploads).toEqual([]);
  }
  async function capture(name,{consoleView=false}={}){
   const started=performance.now();
   const timing={name,stage:'waiting-for-render'};captureTimings.push(timing);
   const expected=schedule.find(item=>item.name===name);expect(expected).toBeTruthy();
   await assertApplicationHealth(expect.soft);
   if(process.env.HEPTA_ROBRIX_FIXTURES==='1'&&!consoleView){
    // HTTP requestfinished precedes Rust resource adoption and the redraw.
    // Wait for the real message renderer's font-family observation, not a sleep.
    await expect.poll(()=>rustFontStates.some(text=>/HEPTA_FIXTURE_FONT_STATE .*loaded_fonts=3 complete=true/.test(text)),{timeout:60000}).toBe(true);
   }
   // A Rust draw observation can precede browser compositing. Cross a real
   // frame boundary before reading pixels; no time-based sleep or retry waiver.
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   phase='snapshot';await page.evaluate(()=>window.__heptaTestPhase='snapshot');
   const path=testInfo.outputPath(name+'.png');const beforeScreenshot=performance.now();const jumpAreaBefore=latestJumpArea();const geometryBefore=geometryObservations.at(-1)??null;
   timing.stage='capturing-png';timing.readyMs=beforeScreenshot-started;
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
   const png=await readFile(path);
   const scale=png.readUInt32BE(16)/page.viewportSize().width;
   expect.soft(png.readUInt32BE(20),'Full-page capture must not have canvas baseline overflow').toBe(Math.round(page.viewportSize().height*scale));
   expect(expected).toBeTruthy();expect(page.viewportSize()).toEqual(expected.viewport);
   const jumpArea=latestJumpArea();
   if(expected.jump){expect(jumpArea).not.toBeNull();expect(jumpArea).toEqual(jumpAreaBefore);}
   timing.stage='complete';timing.screenshotAndReadbackMs=performance.now()-beforeScreenshot;timing.totalMs=performance.now()-started;
   pixelCaptures.push({name,viewport:page.viewportSize(),theme:expected.theme,jumpArea,jumpAreaBefore,geometryBefore,geometryAfter:geometryObservations.at(-1)??null,pngSha256:createHash('sha256').update(png).digest('hex')});
   await assertApplicationHealth(expect.soft);
   return {path,name,jumpArea};
  }
  async function rememberThemeControl(captured){
   const start=performance.now();
   const point=await screenshotWordCenter(captured.path,'Aurora',page.viewportSize().width,{recordOcr:true});
   controlTimings.push({capture:captured.name,word:'Aurora',ms:performance.now()-start});
   themeControlPoints.set(page.viewportSize().width,{...point,sourceCapture:captured.name,sourcePngSha256:pixelCaptures.find(entry=>entry.name===captured.name).pngSha256});
  }
  function latestJumpArea(){
   const text=jumpObservations.findLast(value=>value.includes('HEPTA_FIXTURE_JUMP'))??'';
   const match=text.match(/tail=false visible=true area_valid=true x=([-\d.]+) y=([-\d.]+) width=([-\d.]+) height=([-\d.]+)/);
   if(!match)return null;
   const [x,y,width,height]=match.slice(1).map(Number);return{x,y,width,height};
  }
  async function clickConversationTab(captured,word){
   const start=performance.now();
   expect(['Chat','Console']).toContain(word);
   const tabs=await screenshotConversationTabs(captured.path,page.viewportSize(),{recordOcr:true});
   const point=tabs[word];
   controlTimings.push({capture:captured.name,word,ms:performance.now()-start});
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
   expect(await page.locator('canvas').evaluate(canvas=>canvas.getContext('webgl2')?.getContextAttributes()?.preserveDrawingBuffer)).toBe(true);
   expect(await page.locator('meta[name=viewport]').getAttribute('content')).not.toContain('user-scalable=no');
   let captured;let expectedDraft='Theme round trip draft 中文🚀';
   for(const theme of ['Aurora','Obsidian','Lunar']){
    await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);
    captured=await capture(`robrix-${theme}-${page.viewportSize().width}`);
    if(theme==='Aurora')await rememberThemeControl(captured);
    await page.setViewportSize({width:page.viewportSize().width===1280?640:1280,height:800});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    captured=await capture(`robrix-${theme}-after-resize`);
    if(theme==='Aurora')await rememberThemeControl(captured);
    if(theme==='Aurora'){
     await page.mouse.click(page.viewportSize().width*0.65,720);
     await page.keyboard.insertText(expectedDraft);
     await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(expectedDraft);
     captured=await capture('robrix-draft-before-theme');
    }
    // Both viewport positions came from this run's actual Aurora pixels.
    // The shared theme control stays in that same fixed navigation region.
    // Exact label OCR is a mandatory offline gate; collect all original pixels.
    const point=themeControlPoints.get(page.viewportSize().width);
    expect(point).toBeTruthy();
    await page.mouse.move(point.x,point.y);
    await page.mouse.down();
    // Let the real focus-loss/hover redraw occur while the pointer is held.
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.mouse.up();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.keyboard.type(' kept');expectedDraft+=' kept';
    await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(expectedDraft);
   }
   captured=await capture('robrix-theme-round-trip');
   await clickConversationTab(captured,'Console');
   const consoleCapture=await capture('robrix-console',{consoleView:true});
   await clickConversationTab(consoleCapture,'Chat');
   captured=await capture('robrix-console-round-trip');
   // Re-enter the real Rust editor after the Console round trip. Its native
   // mirror must be repopulated from owner state, including the astral character.
   await page.mouse.click(page.viewportSize().width*0.65,720);
   await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(expectedDraft);
   if(process.env.HEPTA_ROBRIX_FIXTURES==='1'){
    const before=scrollObservations.at(-1)?.travel??0;
    await page.mouse.move(page.viewportSize().width*0.75,350);
    await page.mouse.wheel(0,-480);
    await expect.poll(()=>scrollObservations.at(-1)?.travel??before).toBeGreaterThan(before);
    await expect.poll(()=>jumpObservations.findLast(text=>text.includes('HEPTA_FIXTURE_JUMP'))??'').toMatch(/tail=false visible=true area_valid=true/);
    await capture('robrix-user-scrollback');
    const anchor=scrollObservations.at(-1)?.first;
    const scrollTravel=scrollObservations.at(-1)?.travel;
    const beforeResize=jumpObservations.length;
    await page.setViewportSize({width:page.viewportSize().width===1280?640:1280,height:800});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await expect.poll(()=>jumpObservations.slice(beforeResize).some(text=>text.includes('HEPTA_FIXTURE_JUMP'))).toBe(true);
    await expect.poll(()=>latestJumpArea()).not.toBeNull();
    captured=await capture('robrix-scrollback-after-resize');
    expect(scrollObservations.at(-1)?.travel).toBe(scrollTravel);
    expect(anchor).toBeLessThan(63);
    const jump=captured.jumpArea;expect(jump).toBeTruthy();expect(latestJumpArea()).toEqual(jump);
    expect([jump.x,jump.y,jump.width,jump.height].every(Number.isFinite)).toBe(true);
    expect(jump.width).toBeGreaterThan(0);expect(jump.height).toBeGreaterThan(0);
    expect(jump.x).toBeGreaterThanOrEqual(0);expect(jump.y).toBeGreaterThanOrEqual(0);
    expect(jump.x+jump.width).toBeLessThanOrEqual(page.viewportSize().width);expect(jump.y+jump.height).toBeLessThanOrEqual(page.viewportSize().height);
    await page.mouse.click(jump.x+jump.width/2,jump.y+jump.height/2);
    await expect.poll(()=>scrollObservations.at(-1)?.atEnd).toBe(true);
    captured=await capture('robrix-jump-to-latest');
   }
   await assertApplicationHealth();

  } finally {
   for(const capture of pixelCaptures)capture.observedThemePoint=themeControlPoints.get(capture.viewport.width)??null;
   await writeFile(testInfo.outputPath('pixel-plan.json'),JSON.stringify({sourceSha,browser:browserName,initialWidth:viewport.width,fixtures,captures:pixelCaptures,captureTimings,controlTimings},null,2));
   const observed=await page.evaluate(()=>({violations:window.__cspViolations??[],snapshotStyles:window.__snapshotStyles??[],bootPhase:document.documentElement.dataset.heptaBootPhase??'unobserved',wasmStages:window.__wasmStages??[],readyState:document.readyState,canvas:[...document.querySelectorAll('canvas')].map(canvas=>({width:canvas.width,height:canvas.height})),resources:performance.getEntriesByType('resource').map(item=>({name:item.name,duration:item.duration,bytes:item.transferSize}))})).catch(()=>({}));
   const diagnostics=testInfo.outputPath('host-diagnostics.json');
   await writeFile(diagnostics,JSON.stringify({errors,logs,rustFontStates,scrollObservations,jumpObservations,geometryObservations,uploads,fonts,pendingFonts:[...pendingFonts].map(request=>request.url()),...observed},null,2));
   if(testInfo.status!==testInfo.expectedStatus) console.log(JSON.stringify({scope:'fixture scroll diagnostics; not acceptance',browserName,viewport,scrollObservations,jumpObservations}));
   await testInfo.attach('host-diagnostics',{path:diagnostics,contentType:'application/json'});
  }
 });
}
