import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile,writeFile,copyFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {verifyEvidence,verifyCapture} from '../tools/verify-robrix-evidence.mjs';
import {readScreenshotText} from '../tools/verify-robrix-pixels.mjs';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
test('absent browser plans cannot produce successful offline acceptance',async()=>{
 const root=await mkdtemp(join(tmpdir(),'robrix-missing-evidence-'));
 try{
  const result=await verifyEvidence(root,'1'.repeat(40),true);
  assert.equal(result.passed,false);assert.equal(result.results.length,6);
  assert.ok(result.results.every(row=>row.passed===false&&/ENOENT/.test(row.error)));
 }finally{await rm(root,{recursive:true,force:true});}
});
test('real unreadable glyphs fail deferred exact theme and Chinese checks',async()=>{
 const root=await mkdtemp(join(tmpdir(),'robrix-negative-evidence-'));
 try{
  const source=fileURLToPath(new URL('./fixtures/robrix-render/unreadable-e51a1d0f.png',import.meta.url));
  const path=join(root,'negative.png');await copyFile(source,path);
  const bytes=await readFile(path),text=await readScreenshotText(path);
  await writeFile(join(root,'negative-ocr.txt'),text);
  const viewport={width:1280,height:804};
  const entry={name:'negative',theme:'Aurora',viewport,pngSha256:sha(bytes),ocrSha256:sha(text)};
  const expected={name:'negative',viewport,assertTheme:true,theme:'Aurora',cjk:true};
  const result=await verifyCapture(root,entry,expected);
  assert.deepEqual(result,[{check:'chat-readability',passed:false},{check:'exact-theme',passed:false,expected:'Aurora'},{check:'exact-cjk',passed:false}]);
  await assert.rejects(()=>verifyCapture(root,{...entry,pngSha256:'0'.repeat(64)},expected),/bytes changed/);
 }finally{await rm(root,{recursive:true,force:true});}
});
test('capture contract keeps all static assertions and distinguishes counts',async()=>{
 const {captureSchedule,expectedPixelChecks}=await import('../tools/robrix-pixel-plan.mjs');
 for(const width of [640,1280])for(const fixtures of [false,true]){
  const plan=captureSchedule(width,fixtures);
  assert.equal(plan.length,fixtures?13:10);
  assert.equal(new Set(plan.map(item=>item.name)).size,plan.length);
  for(const item of plan){
   const checks=expectedPixelChecks(item);
   assert.ok(checks.length>0);
   if(item.consoleView)assert.deepEqual(checks,['console-label','console-unavailable-reason']);
   else if(fixtures)assert.ok(checks.includes('visible-message-count')&&checks.includes('owner-message-order'));
  }
  for(const name of ['robrix-draft-before-theme','robrix-Obsidian-after-resize','robrix-Lunar-after-resize','robrix-theme-round-trip','robrix-console-round-trip'])assert.ok(plan.find(item=>item.name===name).draft);
  assert.ok(plan.find(item=>item.name==='robrix-theme-round-trip').kept);
  if(fixtures){assert.equal(plan.filter(item=>item.jump).length,2);assert.ok(plan.at(-1).lastMessage);assert.ok(plan[0].lastMessage);}
 }
});
test('unavailable, moved, and out-of-viewport rendered targets fail closed',async()=>{
 const {prepareObservedAreaForOcr,prepareObservedControlForOcr}=await import('../tools/verify-robrix-pixels.mjs');
 const root=await mkdtemp(join(tmpdir(),'robrix-invalid-region-'));
 const source=fileURLToPath(new URL('./fixtures/robrix-render/unreadable-e51a1d0f.png',import.meta.url));
 try{
  const viewport={width:1280,height:804};
  for(const area of [{x:0,y:0,width:0,height:40},{x:-1,y:0,width:100,height:40},{x:1250,y:0,width:100,height:40},{x:0,y:800,width:100,height:40},{x:NaN,y:0,width:100,height:40}])await assert.rejects(()=>prepareObservedAreaForOcr(source,join(root,'invalid.png'),area,viewport));
  for(const textBounds of [{left:0,top:0,width:0,height:10},{left:-1,top:10,width:20,height:10},{left:0,top:900,width:20,height:10},{left:0,top:0,width:20,height:10}])await assert.rejects(()=>prepareObservedControlForOcr(source,join(root,'invalid-control.png'),{x:100,y:100,textBounds},viewport));
  const bytes=await readFile(source);await copyFile(source,join(root,'jump.png'));await writeFile(join(root,'jump-ocr.txt'),'');
  const entry={name:'jump',theme:'Aurora',viewport,pngSha256:sha(bytes),ocrSha256:sha(''),jumpArea:{x:0,y:0,width:100,height:40},jumpAreaBefore:{x:1,y:0,width:100,height:40}};
  await assert.rejects(()=>verifyCapture(root,entry,{name:'jump',theme:'Aurora',viewport,jump:true}),/target moved/);
 }finally{await rm(root,{recursive:true,force:true});}
});
test('wrong source identity and missing mandatory stages cannot pass aggregate',async()=>{
 const root=await mkdtemp(join(tmpdir(),'robrix-invalid-plan-'));
 const {mkdir}=await import('node:fs/promises');
 try{
  for(const browser of ['chromium','firefox','webkit'])for(const initialWidth of [1280,640]){
   const directory=join(root,`robrix-host-Robrix-host-starts-under-strict-CSP-${initialWidth}-${browser}`);await mkdir(directory);
   await writeFile(join(directory,'pixel-plan.json'),JSON.stringify({sourceSha:'2'.repeat(40),browser,initialWidth,fixtures:true,captures:[]}));
  }
  let result=await verifyEvidence(root,'1'.repeat(40),true);assert.equal(result.passed,false);assert.equal(result.semanticChecks.evaluated,0);
  result=await verifyEvidence(root,'2'.repeat(40),true);assert.equal(result.passed,false);assert.equal(result.captures.required,78);assert.equal(result.captures.passed,0);assert.equal(result.results.length,78);assert.ok(result.results.every(row=>/Missing mandatory capture/.test(row.error)));assert.ok(result.semanticChecks.required>78);
 }finally{await rm(root,{recursive:true,force:true});}
});

test('follow-latest rejects clipped, stale, unfinished and missing final status geometry',async()=>{
 const {validateTailStatusGeometry}=await import('../tools/verify-robrix-evidence.mjs');
 const geometry={frame:10,room:0,epoch:0,total:64,layoutFinalized:true,followLatest:true,atEnd:true,viewport:[0,80,640,605],lastRow:[0,568,640,117],lastStatusVisibleGlyphs:[82,662,70,11],composer:[16,693,608,94]};
 const entry=g=>({viewport:{width:640,height:800},geometryBefore:g,geometryAfter:structuredClone(g)});
 assert.deepEqual(validateTailStatusGeometry(entry(geometry)),{x:78,y:658,width:78,height:19});
 // Actual f96 Lunar geometry: final row bottom724.65 exceeds viewport685.6.
 for(const patch of [{atEnd:false},{lastRow:[0,583.293,640,141.36]},{lastStatusVisibleGlyphs:[82,689.33,70,10.64]},{lastStatusVisibleGlyphs:[0,0,0,0]},{lastRow:null},{layoutFinalized:false},{followLatest:false},{total:63},{viewport:[0,80,640,NaN]}])assert.throws(()=>validateTailStatusGeometry(entry({...geometry,...patch})));
 assert.throws(()=>validateTailStatusGeometry({...entry(geometry),geometryAfter:{...geometry,frame:11}}),/changed during capture/);
 assert.throws(()=>validateTailStatusGeometry({viewport:{width:640,height:800}}),/requires real Rust geometry/);
});
