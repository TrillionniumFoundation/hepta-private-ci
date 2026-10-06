// Synthetic browser keyboard actions in the actual default Rust renderer.
// Neither physical IME nor screen-reader acceptance. No API/owner/refresh calls.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';import {createHash} from 'node:crypto';import {execFileSync} from 'node:child_process';
import {readScreenshotText,screenshotWordCenter,prepareVerifiedRegionForOcr} from '../tools/verify-robrix-pixels.mjs';
import {observedControl,themeLine,requireCompleteText,summarizeAx} from '../tools/keyboard-probe-contract.mjs';
for(const scenario of ['cold-keyboard-entry','draft-theme-round-trip','escape-restores-opener'])test(scenario,async({page},testInfo)=>{
 const sourceSha=execFileSync('git',['--no-replace-objects','rev-parse','--verify','HEAD^{commit}'],{encoding:'utf8'}).trim();
 const events=[],errors=[],fonts=[],captures=[],axObservations=[],rustFocusTrace=[];const pending=new Set();let complete=false;
 const isFont=request=>/\.(?:ttf|otf|woff2?)(?:[?#]|$)/i.test(request.url());
 page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{const text=e.text();if(e.type()==='error')errors.push(text);const marker=text.indexOf('HEPTA_KEYBOARD_FOCUS ');if(marker>=0){if(rustFocusTrace.length>=64||text.length>16384)errors.push('Focus trace exceeded fixed capture bounds');else rustFocusTrace.push(text.slice(marker));}});
 page.on('request',r=>{if(isFont(r)){pending.add(r);fonts.push({event:'request',url:r.url()});}if(/\/api\//.test(r.url()))errors.push('Unexpected API request:'+r.url());});
 page.on('requestfinished',r=>{if(isFont(r)){pending.delete(r);fonts.push({event:'finished',url:r.url()});}});
 page.on('requestfailed',r=>{if(isFont(r)){pending.delete(r);fonts.push({event:'failed',url:r.url(),error:r.failure()?.errorText});}});
 page.on('response',r=>{if(isFont(r.request()))fonts.push({event:'response',url:r.url(),status:r.status()});});
 const frame=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const health=()=>{expect(errors).toEqual([]);expect(fonts.filter(f=>f.event==='failed'||f.event==='response'&&f.status!==200)).toEqual([]);};
 async function start(width){await page.setViewportSize({width,height:800});await page.goto('/');await expect(page.locator('canvas')).toBeVisible();await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});await expect.poll(()=>pending.size,{timeout:60000}).toBe(0);await frame();health();}
 async function capture(name){await frame();health();const path=testInfo.outputPath(name+'.png');await page.screenshot({path,fullPage:true,caret:'initial'});const bytes=await readFile(path),viewport=page.viewportSize();expect(bytes.readUInt32BE(20)).toBe(Math.round(800*bytes.readUInt32BE(16)/viewport.width));const domFocus=await page.evaluate(()=>({tag:document.activeElement?.tagName,className:document.activeElement?.className,textarea:[...document.querySelectorAll('textarea')].map(e=>({value:e.value,start:e.selectionStart,end:e.selectionEnd,active:e===document.activeElement,rect:e.getBoundingClientRect().toJSON()}))}));const row={name,viewport,pngSha256:createHash('sha256').update(bytes).digest('hex'),domFocus};captures.push(row);return{path,row};}
 async function textRegion(captured,name,region,normalization='continuous'){const path=testInfo.outputPath(name+'.png');const proof=await prepareVerifiedRegionForOcr(captured.path,path,region,captured.row.viewport,{normalization});expect(proof.sourcePngSha256).toBe(captured.row.pngSha256);const text=await readScreenshotText(path,{layout:'block'});await writeFile(testInfo.outputPath(name+'.json'),JSON.stringify({...proof,text},null,2));return text;}
 async function key(value){events.push({type:'keyboard',value});await page.keyboard.press(value);await frame();}
 async function ax(name){const client=await page.context().newCDPSession(page);try{const data=await client.send('Accessibility.getFullAXTree');const summary=summarizeAx(data.nodes);axObservations.push({name,viewport:page.viewportSize(),...summary});await writeFile(testInfo.outputPath(name+'-ax.json'),JSON.stringify({sourceSha,observationOnly:true,nodes:data.nodes,summary},null,2));}finally{await client.detach();}}
 const editor={x:416,y:720}; // Known640x800 composer position, not an OCR-observed target.
 try{
  if(scenario==='escape-restores-opener'){await start(1280);await ax('desktop-default');await page.goto('about:blank');}
  await start(640);await ax('compact-default');let shot=await capture('initial');
  if(scenario==='cold-keyboard-entry'){
   await key('Tab');await capture('after-first-tab');await key('Enter');shot=await capture('after-keyboard-entry');
   requireCompleteText(await textRegion(shot,'navigation-heading',{left:20,top:44,width:600,height:48}),'Conversations');
   requireCompleteText(await textRegion(shot,'navigation-back',{left:0,top:144,width:640,height:48}),'Back to conversation');
  }else{
   const draft='Keyboard retained draft 中文🚀';await page.mouse.click(editor.x,editor.y);await page.keyboard.insertText(draft);await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(draft);shot=await capture('seeded-draft');
   if(scenario==='draft-theme-round-trip'){
    const point=await screenshotWordCenter(shot.path,'Aurora',640,{recordOcr:true});observedControl(point,{left:0,top:92,width:640,height:52});
    await key('Shift+Tab');await capture('theme-keyboard-focus');await key('Space');shot=await capture('theme-keyboard-activated');
    requireCompleteText(await textRegion(shot,'theme-line',themeLine(point),'navigation-neutral'),'Obsidian Ice');
    await key('Tab');await page.keyboard.type(' kept');await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(draft+' kept');await capture('draft-after-theme-keyboard');
   }else{
    const opener=await screenshotWordCenter(shot.path,'Conversations',640,{recordOcr:true});observedControl(opener,{left:0,top:92,width:640,height:52});await page.mouse.click(opener.x,opener.y);shot=await capture('navigation-open');
    const search=await screenshotWordCenter(shot.path,'Find',640,{recordOcr:true});observedControl(search,{left:0,top:184,width:640,height:604});await page.mouse.click(search.x,search.y);await page.keyboard.insertText('focus search');await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue('focus search');await capture('navigation-search-focused');
    await key('Escape');shot=await capture('navigation-dismissed');const header=await textRegion(shot,'returned-chat-heading',{left:20,top:44,width:600,height:48});expect(header).toMatch(/Keyboard retained draft/i);
    await key('Space');shot=await capture('navigation-keyboard-reopened');requireCompleteText(await textRegion(shot,'reopened-heading',{left:20,top:44,width:600,height:48}),'Conversations');
    await key('Escape');await page.mouse.click(editor.x,editor.y);await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(draft);await capture('draft-after-search-dismissal');
   }
  }
  health();complete=true;
 }finally{
  await capture('terminal-state').catch(error=>events.push({type:'terminal-capture-failed',error:String(error)}));
  await writeFile(testInfo.outputPath('keyboard-evidence.json'),JSON.stringify({sourceSha,scenario,complete,scope:'3 compact keyboard contracts; AX inventory observation only',physicalImeQualified:false,screenReaderQualified:false,editorPoint:{...editor,kind:'known existing composer position'},events,errors,fonts,rustFocusTrace,focusTraceExpected:process.env.HEPTA_KEYBOARD_FOCUS_TRACE==='1',pendingFonts:[...pending].map(r=>r.url()),captures,axObservations},null,2));
 }
});
