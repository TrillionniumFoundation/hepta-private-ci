// Additional fixture-only real-input regression; the original six host cases and
// their capture/OCR contract remain unchanged. No command or state-setting hook.
import {test,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {prepareObservedAreaForOcr,readScreenshotText} from '../tools/verify-robrix-pixels.mjs';

test('Compact sidebar creates once and preserves both conversations',async({page,browserName},testInfo)=>{
 expect(process.env.HEPTA_ROBRIX_FIXTURES).toBe('1');
 const sourceSha=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
 const states=[],geometry=[],captures=[],inputs=[],errors=[],logs=[],fonts=[],uploads=[];
 const pendingFonts=new Set();let phase='application';
 const font=request=>/\.(?:ttf|otf|woff2?)(?:[?#]|$)/i.test(request.url());
 const current=()=>states.at(-1)??null;
 const currentGeometry=()=>current()?.geometry??null;
 const stateValue=value=>value?Object.fromEntries(Object.entries(value).filter(([key])=>!['sample','frame','receipt','geometryFrame'].includes(key))):null;
 const settle=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 page.on('pageerror',error=>errors.push({phase,message:error.message}));
 page.on('console',message=>{
  const text=message.text();
  if(message.type()==='error')errors.push({phase,message:text});
  if(logs.length<1000)logs.push({phase,type:message.type(),text:text.slice(0,4000)});
  const sidebar=text.match(/HEPTA_FIXTURE_SIDEBAR sample=(\d+) frame=(\d+) receipt=([a-z-]+) (\{.*\})/);
  const room=text.match(/HEPTA_FIXTURE_GEOMETRY frame=(\d+) (\{.*\})/);
  try{
   if(sidebar)states.push({sample:Number(sidebar[1]),frame:Number(sidebar[2]),receipt:sidebar[3],...JSON.parse(sidebar[4])});
   if(room)geometry.push({frame:Number(room[1]),...JSON.parse(room[2])});
  }catch(error){errors.push({phase,message:'Invalid real Rust fixture observation: '+String(error)});}
 });
 page.on('request',request=>{
  if(/\/(?:api\/crash|\$report_error)/.test(request.url()))uploads.push(request.url());
  if(font(request)){pendingFonts.add(request);fonts.push({event:'request',url:request.url()});}
 });
 page.on('requestfinished',request=>{if(font(request)){pendingFonts.delete(request);fonts.push({event:'finished',url:request.url()});}});
 page.on('requestfailed',request=>{if(font(request)){pendingFonts.delete(request);fonts.push({event:'failed',url:request.url(),error:request.failure()?.errorText});}});
 await page.addInitScript(()=>{
  window.__sidebarPhase='application';window.__sidebarCsp=[];window.__sidebarStyles=[];
  document.addEventListener('securitypolicyviolation',event=>window.__sidebarCsp.push({phase:window.__sidebarPhase,directive:event.violatedDirective,blockedURI:event.blockedURI}));
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)if(node.nodeName==='STYLE')window.__sidebarStyles.push({phase:window.__sidebarPhase,text:node.textContent});}).observe(document,{childList:true,subtree:true});
 });
 function center(area){
  expect(area,'A current real draw Area is required').toHaveLength(4);
  const [x,y,width,height]=area,viewport=page.viewportSize();
  expect(area.every(Number.isFinite)).toBe(true);expect(width).toBeGreaterThan(0);expect(height).toBeGreaterThan(0);
  expect(x).toBeGreaterThanOrEqual(0);expect(y).toBeGreaterThanOrEqual(0);
  expect(x+width).toBeLessThanOrEqual(viewport.width);expect(y+height).toBeLessThanOrEqual(viewport.height);
  return{x:x+width/2,y:y+height/2};
 }
 async function health(){
  expect(errors.filter(value=>value.phase==='application')).toEqual([]);
  expect(await page.evaluate(()=>window.__sidebarCsp.filter(value=>value.phase==='application'))).toEqual([]);
  expect(uploads).toEqual([]);expect(fonts.filter(value=>value.event==='failed')).toEqual([]);
 }
 async function capture(name){
  await expect.poll(()=>pendingFonts.size,{timeout:60000}).toBe(0);
  await settle();await health();
  const before=current(),geometryBefore=currentGeometry();expect(before).not.toBeNull();
  const viewport=page.viewportSize();
  const metrics=await page.locator('canvas').evaluate(canvas=>({dpr:devicePixelRatio,css:{x:canvas.getBoundingClientRect().x,y:canvas.getBoundingClientRect().y,width:canvas.getBoundingClientRect().width,height:canvas.getBoundingClientRect().height},buffer:{width:canvas.width,height:canvas.height},retained:canvas.getContext('webgl2')?.getContextAttributes()?.preserveDrawingBuffer}));
  expect(metrics.css).toEqual({x:0,y:0,...viewport});expect(metrics.retained).toBe(true);
  expect(metrics.buffer).toEqual({width:Math.round(viewport.width*metrics.dpr),height:Math.round(viewport.height*metrics.dpr)});
  if(!before.navigationOpen&&!before.consoleOpen){expect(geometryBefore).not.toBeNull();expect(geometryBefore.room).toBe(before.active);}
  const path=testInfo.outputPath(name+'.png');
  phase='snapshot';await page.evaluate(()=>window.__sidebarPhase='snapshot');
  try{await page.screenshot({path,fullPage:true,caret:'initial'});}
  finally{phase='application';await page.evaluate(()=>window.__sidebarPhase='application');}
  const snapshot=await page.evaluate(()=>({violations:window.__sidebarCsp.filter(value=>value.phase==='snapshot'),styles:window.__sidebarStyles.filter(value=>value.phase==='snapshot')}));
  const snapshotErrors=errors.filter(value=>value.phase==='snapshot');
  if(snapshot.violations.length||snapshotErrors.length){
   expect(['webkit','firefox']).toContain(browserName);expect(snapshot.styles.length).toBeGreaterThan(0);
   expect(snapshot.styles.every(value=>value.text==='body {}')).toBe(true);
   expect(snapshot.violations.every(value=>value.directive==='style-src-elem'&&value.blockedURI==='inline')).toBe(true);
   expect(snapshot.violations.length).toBeLessThanOrEqual(snapshot.styles.length*2);
   expect(snapshotErrors.every(value=>/Refused to apply a stylesheet/.test(value.message))).toBe(true);
   expect(snapshotErrors.length).toBeLessThanOrEqual(snapshot.styles.length*2);
  }
  const png=await readFile(path),width=png.readUInt32BE(16),height=png.readUInt32BE(20);
  expect(width).toBe(Math.round(viewport.width*metrics.dpr));expect(height).toBe(Math.round(viewport.height*metrics.dpr));
  const after=current(),geometryAfter=currentGeometry();
  expect(stateValue(after),'State and draw areas must remain stable across this exact PNG').toEqual(stateValue(before));
  expect(geometryAfter).toEqual(geometryBefore);
  const value={name,path,viewport,metrics,pngSize:{width,height},pngSha256:createHash('sha256').update(png).digest('hex'),before,after,geometryBefore,geometryAfter};
  captures.push(value);await health();return value;
 }
 async function waitRoomDraw(afterFrame){
  await expect.poll(()=>current()?.geometryFrame).toBeGreaterThan(afterFrame);
  await expect.poll(()=>currentGeometry()?.room).toBe(current().active);
 }
 async function resizeTo(viewport){
  const afterFrame=current().geometryFrame;await page.setViewportSize(viewport);await waitRoomDraw(afterFrame);await settle();
 }
 async function clickControl(name){
  const observed=await capture('before-'+name+'-'+inputs.length),area=observed.after.controls[name],point=center(area);
  expect(current().controls[name]).toEqual(area);
  inputs.push({kind:'click',control:name,area,point,sourceCapture:observed.name,sourcePngSha256:observed.pngSha256});
  await page.mouse.click(point.x,point.y);await settle();
  if(['backToChat','chat'].includes(name))await waitRoomDraw(observed.after.geometryFrame);
 }
 async function selectRoom(room){
  await clickControl('conversations');await expect.poll(()=>current()?.navigationOpen).toBe(true);
  await expect.poll(()=>current()?.targets?.rooms.some(value=>value.room===room&&value.area!==null)).toBe(true);
  const observed=await capture('select-room-'+room+'-'+inputs.length);
  const area=observed.after.targets.rooms.find(value=>value.room===room).area,point=center(area);
  inputs.push({kind:'click',control:'room',room,area,point,sourceCapture:observed.name,sourcePngSha256:observed.pngSha256});
  await page.mouse.click(point.x,point.y);await expect.poll(()=>current()?.active).toBe(room);
  await expect.poll(()=>current()?.navigationOpen).toBe(false);await waitRoomDraw(observed.after.geometryFrame);await settle();
 }
 async function editorText(expected,{write=false}={}){
  await clickControl('editor');
  if(write)await page.keyboard.insertText(expected);
  await expect(page.locator('textarea.cx_webgl_textinput')).toHaveValue(expected);
  await expect.poll(()=>current()?.draftBytes).toBe(Buffer.byteLength(expected));
 }
 let original,newRoom,anchor;
 try{
  await page.setViewportSize({width:640,height:800});await page.goto('/');
  await expect(page.locator('canvas')).toBeVisible();await expect(page.locator('.canvas_loader')).toBeHidden({timeout:60000});
  await expect.poll(()=>logs.some(value=>/HEPTA_FIXTURE_FONT_STATE .*loaded_fonts=3 complete=true/.test(value.text)),{timeout:60000}).toBe(true);
  await expect.poll(()=>current()?.count).toBe(1);await expect.poll(()=>currentGeometry()?.total).toBe(64);
  original=current().active;const originalIds=[...current().draftIds];
  const originalText='Original room draft 中文 preserved';
  const newText='New local draft 中文 retained';
  await editorText(originalText,{write:true});
  const beforeScroll=await capture('original-before-scroll'),point=center(beforeScroll.geometryAfter.viewport);
  inputs.push({kind:'wheel',point,deltaY:-480,sourceCapture:beforeScroll.name,sourcePngSha256:beforeScroll.pngSha256});
  await page.mouse.move(point.x,point.y);await page.mouse.wheel(0,-480);
  await expect.poll(()=>currentGeometry()?.followLatest).toBe(false);
  anchor=(await capture('original-scrollback')).geometryAfter;
  expect(anchor.first).toBeLessThan(63);expect(anchor.travel).toBeGreaterThan(0);
  await clickControl('conversations');await expect.poll(()=>current()?.navigationOpen).toBe(true);
  await expect.poll(()=>current()?.targets?.newDraft?.length).toBe(4);
  const open=await capture('sidebar-open'),targets=open.after.targets;
  expect(targets.newDraft.slice(2)).toEqual([104,44]);expect(targets.newDraftClipped).toEqual(targets.newDraft);expect(targets.search[3]).toBe(40);
  for(const [key,pattern] of [['brand',/\bHEPTA\b/],['group',/\bCONVERSATIONS\b/],['newDraft',/\bNew\s+draft\b/i]]){
   const area=targets[key];center(area);const path=testInfo.outputPath('sidebar-'+key+'-ocr.png');
   const region=await prepareObservedAreaForOcr(open.path,path,{x:area[0],y:area[1],width:area[2],height:area[3]},open.viewport);
   const text=await readScreenshotText(path,{layout:'block'});await writeFile(testInfo.outputPath('sidebar-'+key+'-ocr.txt'),text);
   expect(text).toMatch(pattern);open[key+'Ocr']={region,text};
  }
  const oldHitbox=targets.newDraft,newPoint=center(oldHitbox);
  inputs.push({kind:'click',control:'newDraft',area:oldHitbox,point:newPoint,sourceCapture:open.name,sourcePngSha256:open.pngSha256});
  await page.mouse.click(newPoint.x,newPoint.y);
  await expect.poll(()=>current()?.count).toBe(2);await expect.poll(()=>current()?.navigationOpen).toBe(false);
  await waitRoomDraw(open.after.geometryFrame);
  newRoom=current().active;expect(originalIds).not.toContain(newRoom);
  expect(current().draftIds.filter(id=>!originalIds.includes(id))).toEqual([newRoom]);
  const expectedIds=[...current().draftIds];await capture('after-one-new-draft');
  // Crucially test retained keyboard focus BEFORE any click can move it away.
  for(const key of ['Enter','Space']){
   const previous=current().sample;inputs.push({kind:'key',key,before:current()});
   await page.keyboard.press(key);
   await expect.poll(()=>states.some(value=>value.sample>previous&&value.receipt==='key-up')).toBe(true);
   await capture('closed-sidebar-'+key);expect(current().draftIds).toEqual(expectedIds);expect(current().count).toBe(2);
   expect(current().active).toBe(newRoom);expect(current().navigationOpen).toBe(false);
  }
  inputs.push({kind:'old-hitbox-click',point:newPoint,area:oldHitbox,sourceCapture:open.name,sourcePngSha256:open.pngSha256});
  const beforeOldClick=current().sample;await page.mouse.click(newPoint.x,newPoint.y);
  await expect.poll(()=>states.some(value=>value.sample>beforeOldClick&&value.receipt==='mouse-up')).toBe(true);
  await capture('closed-sidebar-old-hitbox');expect(current().draftIds).toEqual(expectedIds);expect(current().active).toBe(newRoom);
  expect(current().navigationOpen).toBe(false);expect(current().draftBytes).toBe(0);
  await editorText(newText,{write:true});await capture('new-draft-edited');
  await selectRoom(original);await editorText(originalText);
  await expect.poll(()=>currentGeometry()?.room).toBe(original);await expect.poll(()=>currentGeometry()?.followLatest).toBe(false);
  const returned=(await capture('original-room-return')).geometryAfter;
  expect(returned.total).toBe(64);expect(returned.first).toBe(anchor.first);expect(returned.offset).toBe(anchor.offset);
  await selectRoom(newRoom);await editorText(newText);await capture('new-draft-return');
  await clickControl('conversations');await expect.poll(()=>current()?.navigationOpen).toBe(true);
  await clickControl('backToChat');await expect.poll(()=>current()?.navigationOpen).toBe(false);
  await editorText(newText);
  await resizeTo({width:1280,height:800});await capture('desktop-adaptive-return');
  await resizeTo({width:640,height:800});await editorText(newText);await capture('compact-adaptive-return');
  await clickControl('console');await expect.poll(()=>current()?.consoleOpen).toBe(true);await capture('console-open');
  await clickControl('chat');await expect.poll(()=>current()?.consoleOpen).toBe(false);await editorText(newText);
  for(const theme of ['Obsidian Ice','Lunar Titanium','Aurora Graphite']){
   await clickControl('theme');await expect.poll(()=>current()?.theme).toBe(theme);
   await editorText(newText);await clickControl('conversations');await expect.poll(()=>current()?.navigationOpen).toBe(true);
   await capture('sidebar-'+theme.split(' ')[0]);
   await clickControl('backToChat');await expect.poll(()=>current()?.navigationOpen).toBe(false);
  }
  await selectRoom(original);await editorText(originalText);
  const finalOriginal=(await capture('original-final-return')).geometryAfter;
  expect(finalOriginal.total).toBe(64);expect(finalOriginal.first).toBe(anchor.first);expect(finalOriginal.offset).toBe(anchor.offset);expect(finalOriginal.followLatest).toBe(false);
  await selectRoom(newRoom);await editorText(newText);await capture('new-final-return');
  expect(current().draftIds).toEqual(expectedIds);expect(current().count).toBe(2);await health();
 }finally{
  const observed=await page.evaluate(()=>({violations:window.__sidebarCsp??[],snapshotStyles:window.__sidebarStyles??[]})).catch(()=>({}));
  const path=testInfo.outputPath('sidebar-evidence.json');
  await writeFile(path,JSON.stringify({sourceSha,browser:browserName,fixtures:true,status:testInfo.status,expectedStatus:testInfo.expectedStatus,original,newRoom,anchor,captures,inputs,states,geometry,errors,logs,fonts,pendingFonts:[...pendingFonts].map(request=>request.url()),uploads,...observed},null,2));
  await testInfo.attach('sidebar-evidence',{path,contentType:'application/json'});
 }
});
