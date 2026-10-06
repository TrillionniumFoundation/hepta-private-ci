// Actual default Rust renderer: new breakpoint coverage, no gateway or owner fixture.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {screenshotWordCenter,readScreenshotText,prepareVerifiedRegionForOcr} from '../tools/verify-robrix-pixels.mjs';
import {breakpointWidths,breakpointThemes,headingRegion,navigationRegion,requireObservedPoint,consoleRegion,themeTextRegion,requireThemeText,requireAuthorityWarning} from '../tools/robrix-breakpoint-plan.mjs';
for(const theme of breakpointThemes)for(const width of breakpointWidths)test(`Console breakpoint ${theme} ${width}`,async({page},testInfo)=>{
 const sourceSha=execFileSync('git',['--no-replace-objects','rev-parse','--verify','HEAD^{commit}'],{encoding:'utf8'}).trim();
 // Known existing compact composer position at759x800, not an OCR-observed target.
 // The actual focused SDK textarea and retained draft value are verified after each click.
 const editorPoint={x:759*0.65,y:720};
 const captures=[],errors=[],fontEvents=[],apiRequests=[];const pendingFonts=new Set();let currentTheme='Aurora';let completed=false;
 const font=request=>/\.(?:ttf|otf|woff2?)(?:[?#]|$)/i.test(request.url());
 const frame=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
 page.on('request',request=>{if(font(request)){pendingFonts.add(request);fontEvents.push({event:'request',url:request.url()});}if(/\/api\//.test(request.url()))apiRequests.push(request.url());});
 page.on('response',response=>{if(font(response.request()))fontEvents.push({event:'response',url:response.url(),status:response.status()});});
 page.on('requestfinished',request=>{if(font(request)){pendingFonts.delete(request);fontEvents.push({event:'finished',url:request.url()});}});
 page.on('requestfailed',request=>{if(font(request)){pendingFonts.delete(request);fontEvents.push({event:'failed',url:request.url(),error:request.failure()?.errorText});}});
 const health=()=>{expect(errors).toEqual([]);expect(apiRequests).toEqual([]);expect(fontEvents.filter(item=>item.event==='failed'||item.event==='response'&&item.status!==200)).toEqual([]);};
 async function capture(name){
  await frame();health();await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);
  const path=testInfo.outputPath(name+'.png');await page.screenshot({path,fullPage:true,caret:'initial'});const bytes=await readFile(path);const viewport=page.viewportSize();
  expect(bytes.readUInt32BE(20)).toBe(Math.round(viewport.height*bytes.readUInt32BE(16)/viewport.width));
  const row={name,theme:currentTheme,viewport,pngSha256:createHash('sha256').update(bytes).digest('hex')};captures.push(row);
  const text=await readScreenshotText(path);await writeFile(testInfo.outputPath(name+'-ocr.txt'),text);health();return{path,text,row};
 }
 async function regionText(captured,name,region,normalization='continuous'){
  const path=testInfo.outputPath(name+'.png');const proof=await prepareVerifiedRegionForOcr(captured.path,path,region,captured.row.viewport,{normalization});
  expect(proof.sourcePngSha256).toBe(captured.row.pngSha256);
  const text=await readScreenshotText(path,{layout:'block'});await writeFile(testInfo.outputPath(name+'-ocr.txt'),text);await writeFile(testInfo.outputPath(name+'-source.json'),JSON.stringify(proof,null,2));return text;
 }
 async function clickTab(captured,word){const point=await screenshotWordCenter(captured.path,word,page.viewportSize().width,{recordOcr:true});requireObservedPoint(point,navigationRegion(page.viewportSize(),theme));await page.mouse.click(point.x,point.y);await frame();}
 try{
  // Start all subjects in compact view;760/761 cross the real adaptive boundary.
  await page.setViewportSize({width:759,height:800});await page.goto('/');await expect(page.locator('canvas')).toBeVisible();await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);
  let captured=await capture('initial-chat');
  for(const [index,current] of breakpointThemes.slice(0,breakpointThemes.indexOf(theme)).entries()){
   const point=await screenshotWordCenter(captured.path,current,759,{recordOcr:true});requireObservedPoint(point,{left:0,top:92,width:759,height:104});await page.mouse.click(point.x,point.y);currentTheme=breakpointThemes[index+1];captured=await capture('theme-after-'+current);
   requireThemeText(await regionText(captured,'theme-line-after-'+current,themeTextRegion(captured.row.viewport,point),'navigation-neutral'),currentTheme);
  }
  if(theme==='Aurora'){const point=await screenshotWordCenter(captured.path,'Aurora',759,{recordOcr:true});requireThemeText(await regionText(captured,'initial-theme-line',themeTextRegion(captured.row.viewport,point),'navigation-neutral'),theme);}
  const draft='Breakpoint retained draft 中文🚀';await page.mouse.click(editorPoint.x,editorPoint.y);await page.keyboard.insertText(draft);await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(draft);
  if(width===759){await page.setViewportSize({width:760,height:800});await frame();}
  captured=await capture('draft-before-console');await clickTab(captured,'Console');
  await page.setViewportSize({width,height:800});await frame();
  await page.mouse.move(width-35,400);await page.mouse.wheel(0,-3000);await frame();
  const top=await capture('console-top');
  const topText=await regionText(top,'console-top-body',consoleRegion(top.row.viewport,theme));
  expect(topText).toMatch(/Runtime\s+observations/i);expect(topText).toMatch(/Production\s+owner/i);expect(topText).toMatch(/Not\s+requested/i);
  const crop=testInfo.outputPath('console-heading.png');const observed=await prepareVerifiedRegionForOcr(top.path,crop,headingRegion(page.viewportSize(),theme),page.viewportSize());expect(observed.sourcePngSha256).toBe(top.row.pngSha256);
  const heading=await readScreenshotText(observed.rawPath??crop,{layout:'block'});expect(heading.trim()).toMatch(/^Console\s*$/i);
  await page.mouse.move(width-35,500);await page.mouse.wheel(0,3000);await frame();
  const bottom=await capture('console-bottom');
  const bottomText=await regionText(bottom,'console-bottom-body',consoleRegion(bottom.row.viewport,theme));
  expect(bottomText).toMatch(/Legacy\s+runtime\s+observation/i);
  const warning=requireAuthorityWarning(bottomText);await writeFile(testInfo.outputPath('authority-warning-proof.json'),JSON.stringify({...warning,sourcePngSha256:bottom.row.pngSha256},null,2));
  // Return across the breakpoint while still in Console; then restore the same editor.
  await page.setViewportSize({width:759,height:800});await frame();await page.mouse.move(724,400);await page.mouse.wheel(0,-3000);captured=await capture('console-before-return');await clickTab(captured,'Chat');
  await page.mouse.click(editorPoint.x,editorPoint.y);await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(draft);
  captured=await capture('chat-after-return');expect(captured.text).toMatch(/Breakpoint retained draft/i);health();completed=true;
 }finally{
  await writeFile(testInfo.outputPath('breakpoint-evidence.json'),JSON.stringify({sourceSha,theme,targetWidth:width,completed,editorPoint:{...editorPoint,kind:'known existing compact composer position, not OCR'},scope:'Chromium default Console/draft at360/759/760/761; no live owner or physical IME',captures,errors,fontEvents,pendingFonts:[...pendingFonts].map(request=>request.url()),apiRequests},null,2));
 }
});
