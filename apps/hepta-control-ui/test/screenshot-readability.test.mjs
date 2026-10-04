import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {readScreenshotText,requireChatText,screenshotWordCenter,prepareScreenshotForOcr,prepareObservedControlForOcr,conversationTabsFromOcr,screenshotConversationTabs,sourcePixelRegion,prepareVerifiedRegionForOcr,rebaseNavigationOcr} from '../tools/verify-robrix-pixels.mjs';
import {validateFixtureTextRegion,fixtureMessageObservation,validateTailStatusGeometry} from '../tools/verify-robrix-evidence.mjs';
test('real Chromium glyph-block failure cannot pass chat readability',async()=>{
 const path=fileURLToPath(new URL('./fixtures/robrix-render/unreadable-e51a1d0f.png',import.meta.url));
 for(const layout of ['sparse','block']){
  const text=await readScreenshotText(path,{layout});
  assert.throws(()=>requireChatText(text),/Actual canvas screenshot/);
 }
 await assert.rejects(()=>screenshotWordCenter(path,'Console',1280,{topOnly:true}),/must be readable before activation/);
 const directory=await mkdtemp(join(tmpdir(),'robrix-ocr-negative-'));
 try{
  const normalized=await prepareScreenshotForOcr(path,join(directory,'normalized.png'));
  const text=await readScreenshotText(normalized,{language:'eng+chi_sim'});
  assert.throws(()=>requireChatText(text),/Actual canvas screenshot/);
  assert.doesNotMatch(text.replace(/\s+/g,''),/中文输入|键盘焦点|滚动位置/);
  const regionPath=join(directory,'control-region.png');
  // The historical failing PNG includes the old four-pixel canvas overflow.
  await prepareObservedControlForOcr(path,regionPath,{x:157.5,y:768},{width:1280,height:804});
  assert.doesNotMatch(await readScreenshotText(regionPath,{layout:'block'}),/Aurora|Obsidian|Lunar/);
  await assert.rejects(()=>prepareObservedControlForOcr(path,regionPath,{x:-1,y:768},{width:1280,height:804}),/observed inside/);
 }finally{await rm(directory,{recursive:true,force:true});}
});

const viewport={width:1280,height:800};
const chat={text:'Chat',left:343,top:176,width:29,height:11};
const consoleTab={text:'Console',left:422,top:176,width:52,height:11};
const header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext';
function tsv(words,scale=1){
 return [header,...words.map((word,index)=>[5,1,1,1,1,index+1,...['left','top','width','height'].map(key=>word[key]*scale),word.conf??95,word.text].join('\t'))].join('\n');
}
function select(words,{scale=1,size={width:1280*scale,height:800*scale}}={}){
 return conversationTabsFromOcr(tsv(words,scale),size,viewport);
}
test('navigation glyph centers map screenshot pixels back to CSS pixels',()=>{
 const normal=select([chat,consoleTab]);
 assert.deepEqual(select([chat,consoleTab],{scale:2}),normal);
 assert.deepEqual(normal.Chat,{x:357.5,y:181.5,textBounds:{left:343,top:176,width:29,height:11}});
 assert.deepEqual(normal.Console,{x:448,y:181.5,textBounds:{left:422,top:176,width:52,height:11}});
});
test('body words cannot replace absent navigation controls',()=>{
 const body=[{...chat,top:352},{...consoleTab,top:352}];
 assert.equal(select(body),null);
 assert.equal(select([chat,{...consoleTab,top:377}]),null);
 assert.deepEqual(select([chat,consoleTab,...body]),select([chat,consoleTab]));
});
test('multiple navigation labels are rejected instead of ranking confidence',()=>{
 assert.throws(()=>select([chat,consoleTab,{...chat,left:600},{...consoleTab,left:680}]),/Ambiguous/);
 assert.throws(()=>select([chat,{...consoleTab,conf:99},{...consoleTab,left:600,conf:1}]),/Ambiguous/);
});
test('separate rows and reversed labels do not form the navigation pair',()=>{
 assert.throws(()=>select([{...chat,top:161},{...consoleTab,top:185}]),/one left-to-right rendered navigation row/);
 assert.throws(()=>select([{...chat,left:500},consoleTab]),/one left-to-right rendered navigation row/);
});
test('partially clipped labels and malformed glyph bounds cannot activate',()=>{
 assert.throws(()=>select([{...chat,left:300},consoleTab]),/completely inside/);
 assert.throws(()=>select([chat,{...consoleTab,top:199}]),/completely inside/);
 assert.throws(()=>select([chat,{...consoleTab,width:0}]),/finite and positive/);
 assert.throws(()=>select([chat,{...consoleTab,left:NaN}]),/finite and positive/);
});
test('missing or non-exact labels remain unreadable',()=>{
 assert.equal(select([]),null);
 assert.equal(select([consoleTab]),null);
 assert.equal(select([{...chat,text:'Chatty'},{...consoleTab,text:'Console:'}]),null);
});
test('unknown viewport and overflowing full-page screenshot are rejected',()=>{
 assert.throws(()=>select([chat,consoleTab],{size:{width:1280,height:804}}),/full-viewport/);
 assert.throws(()=>conversationTabsFromOcr(tsv([chat,consoleTab]),{width:400,height:800},{width:400,height:800}),/explicitly covered viewport/);
});

const fixtureRoot=new URL('./fixtures/robrix-render/',import.meta.url);
const sources=JSON.parse(await readFile(new URL('header-navigation-266-source.json',fixtureRoot),'utf8'));
for(const source of sources){
 test(`real 266 pixels select only the visible tab pair: ${source.fixture}`,async()=>{
  const path=fileURLToPath(new URL(source.fixture,fixtureRoot));
  const png=await readFile(path);
  assert.equal(createHash('sha256').update(png).digest('hex'),source.sha256);
  // Retain the actual failure of the retired location assumption as a control.
  await assert.rejects(()=>screenshotWordCenter(path,'Console',source.actual_viewport.width,{topOnly:true}),/must be readable before activation/);
  const observed=await screenshotConversationTabs(path,source.actual_viewport);
  assert.ok(observed.Chat.x<observed.Console.x);
  assert.ok(observed.Console.y>90);
  assert.ok(observed.Console.y<observed.region.top+observed.region.height);
 });
}
test('the retained unreadable renderer cannot pass the new navigation selector',async()=>{
 const path=fileURLToPath(new URL('unreadable-e51a1d0f.png',fixtureRoot));
 await assert.rejects(()=>screenshotConversationTabs(path,viewport),/full-viewport|must be readable/);
});

test('fixed navigation crop coordinates return to source and CSS pixels at DPR two',()=>{
 const imageSize={width:2560,height:1600},processedSize={width:5832,height:312};
 const cropped=tsv([{text:'Chat',left:210,top:120,width:174,height:66},{text:'Console',left:684,top:120,width:312,height:66}]);
 const rebased=rebaseNavigationOcr(cropped,imageSize,viewport,processedSize);
 assert.deepEqual(conversationTabsFromOcr(rebased,imageSize,viewport),select([chat,consoleTab]));
 assert.throws(()=>rebaseNavigationOcr(cropped,imageSize,viewport,{...processedSize,width:5833}),/fixed source crop/);
 assert.throws(()=>rebaseNavigationOcr(tsv([{...chat,left:-1}]),imageSize,viewport,processedSize),/actual processed region/);
});
test('crop context cannot hide a navigation glyph crossing the original band',()=>{
 const processedSize={width:2916,height:156};
 const crossing=tsv([{...chat,left:6,top:60},{...consoleTab,left:339,top:60}]);
 const rebased=rebaseNavigationOcr(crossing,viewport,viewport,processedSize);
 assert.throws(()=>conversationTabsFromOcr(rebased,viewport,viewport),/completely inside/);
 for(const row of [{...chat,left:0,top:60},{...chat,left:102,top:0}]){
  assert.throws(()=>rebaseNavigationOcr(tsv([row]),viewport,viewport,processedSize),/crop edge/);
 }
});
test('crop conversion checks viewport, fractional edges and region bounds before processing',()=>{
 assert.deepEqual(sourcePixelRegion({left:10.25,top:20.5,width:40.5,height:30.25},{width:640,height:400},{width:1280,height:800}),{left:20,top:41,width:82,height:61});
 for(const area of [{left:-1,top:0,width:10,height:10},{left:1270,top:0,width:20,height:10},{left:0,top:0,width:0,height:10},{left:NaN,top:0,width:10,height:10}])assert.throws(()=>sourcePixelRegion(area,viewport,viewport),/Region/);
 assert.throws(()=>sourcePixelRegion({left:0,top:0,width:10,height:10},viewport,{width:1280,height:804}),/full-viewport/);
});
test('message count uses distinct exact ordinals from one result without losing order',()=>{
 assert.deepEqual(fixtureMessageObservation('[Fixture 62] first\n[Fixture 64] last',64),{ordinals:[62,64],count:2,countPassed:true,orderPassed:true});
 for(const text of ['', 'Fixture 64', 'Fixture 64\nFixture 64', 'Synthetic placeholders only', 'F ixture 62','Fixture 0\nFixture 1','Fixture 64\nFixture 999','NotFixture 1\nNotFixture 2','前Fixture 1\n前Fixture 2','Fixture 1.5\nFixture 2.5','Fixture 1\nFixture 2\nFixture 1000','Fixture 1\nFixture 2\nFixture 1e3','Fixture 1\nFixture 2\nFixture -3','Fixture 1\nFixture 2\nFixture ]','Fixture 1\nFixture 2\nFixture 03']){
  const result=fixtureMessageObservation(text,64);assert.equal(result.countPassed,false);assert.equal(result.orderPassed,false);
 }
 assert.equal(fixtureMessageObservation('Fixture 64\nFixture 62',64).orderPassed,false);
 // Two insufficient results are not an accepted input to be accumulated.
 assert.throws(()=>fixtureMessageObservation(['Fixture 62','Fixture 64'],64),/one independent OCR string/);
 assert.throws(()=>fixtureMessageObservation('Fixture 1\nFixture 2',0),/actual rendered population/);
});

const regionSources=JSON.parse(await readFile(new URL('region-d212-source.json',fixtureRoot),'utf8'));
const actualEntry=regionSources.find(source=>source.role==='messages-tail').entry;
test('region observations reject missing, synthetic, changing, overlapping or out-of-view geometry',()=>{
 assert.deepEqual(validateFixtureTextRegion(actualEntry,'viewport'),{left:318,top:245.99999904632568,width:962,height:439.60000133514404});
 for(const mutate of [
  e=>{e.geometryBefore=null;},
  e=>{e.geometryBefore.layoutFinalized=false;e.geometryAfter=structuredClone(e.geometryBefore);},
  e=>{e.geometryBefore.frame=0;e.geometryAfter=structuredClone(e.geometryBefore);},
  e=>{e.geometryAfter.frame++;},
  e=>{e.geometryBefore.viewport[0]=-1;e.geometryAfter=structuredClone(e.geometryBefore);},
  e=>{e.geometryBefore.viewport[2]=NaN;e.geometryAfter=structuredClone(e.geometryBefore);},
  e=>{e.geometryBefore.composer[1]=60;e.geometryAfter=structuredClone(e.geometryBefore);},
  e=>{e.geometryBefore.composer[2]=2000;e.geometryAfter=structuredClone(e.geometryBefore);},
 ]){const changed=structuredClone(actualEntry);mutate(changed);assert.throws(()=>validateFixtureTextRegion(changed,'composer'));}
});
for(const source of regionSources){
 test(`real d212 region preserves the original pixel requirement: ${source.role}`,async()=>{
  const path=fileURLToPath(new URL(source.fixture,fixtureRoot));const png=await readFile(path);
  assert.equal(createHash('sha256').update(png).digest('hex'),source.sha256);
  if(source.role==='navigation'){
   const controls=await screenshotConversationTabs(path,source.entry.viewport);
   assert.ok(controls.Chat.y>92&&controls.Chat.y<144);assert.ok(controls.Console.x>controls.Chat.x);
   return;
  }
  const directory=await mkdtemp(join(tmpdir(),'robrix-region-regression-'));
  try{
   const kind=source.role==='draft'?'composer':'viewport';const area=validateFixtureTextRegion(source.entry,kind);
   const output=join(directory,'actual-region.png');const input=await prepareVerifiedRegionForOcr(path,output,area,source.entry.viewport);
   assert.equal(input.sourcePngSha256,source.sha256);
   const text=await readScreenshotText(output,{layout:'block'});
   if(source.role==='draft')assert.match(text,/Theme round trip draft/i);
   else{const observed=fixtureMessageObservation(text,source.entry.geometryBefore.total);assert.equal(observed.countPassed,true);assert.equal(observed.orderPassed,true);}
  }finally{await rm(directory,{recursive:true,force:true});}
 });
}

const webkitSources=JSON.parse(await readFile(new URL('webkit-010-source.json',fixtureRoot),'utf8'));
for(const source of webkitSources){
 test(`real WebKit 010 pixels retain exact requirements: ${source.role}`,async()=>{
  const path=fileURLToPath(new URL(source.fixture,fixtureRoot));
  const bytes=await readFile(path);assert.equal(createHash('sha256').update(bytes).digest('hex'),source.sha256);
  if(source.role==='navigation'){
   const result=await screenshotConversationTabs(path,source.entry.viewport);
   assert.equal(result.normalization,'navigation-binary');
   assert.equal(result.sourcePngSha256,source.sha256);
   assert.ok(result.Chat.x<result.Console.x);
   assert.ok(result.Console.y>92&&result.Console.y<144);
  }else{
   const g=source.entry.geometryBefore;
   assert.ok(g.viewport[0]+g.viewport[2]>source.entry.viewport.width);
   const before=structuredClone(source.entry);
   const area=validateFixtureTextRegion(source.entry,'viewport');
   assert.equal(area.left+area.width,source.entry.viewport.width);
   assert.deepEqual(source.entry,before,'Raw allocation evidence must not be rewritten');
   validateTailStatusGeometry(source.entry);
   const directory=await mkdtemp(join(tmpdir(),'robrix-webkit-regression-'));
   try{
    const output=join(directory,'visible-timeline.png');
    const input=await prepareVerifiedRegionForOcr(path,output,area,source.entry.viewport);
    assert.equal(input.sourcePngSha256,source.sha256);
    const observed=fixtureMessageObservation(await readScreenshotText(output,{layout:'block'}),g.total);
    assert.equal(observed.countPassed,true);assert.equal(observed.orderPassed,true);
   }finally{await rm(directory,{recursive:true,force:true});}
  }
  assert.deepEqual(await readFile(path),bytes);
 });
}
test('visible timeline intersection cannot rescue invisible panes, clipped composer or tail glyphs',()=>{
 const entry=webkitSources.find(source=>source.role==='messages').entry;
 for(const mutate of [
  g=>{g.viewport[0]=1280;},g=>{g.viewport[0]=-1;},g=>{g.viewport[2]=0;},
  g=>{g.viewport[1]=790;},g=>{g.composer[2]=1000;},
  g=>{g.composer[1]=g.viewport[1]+20;},
 ]){
  const bad=structuredClone(entry);mutate(bad.geometryBefore);bad.geometryAfter=structuredClone(bad.geometryBefore);
  assert.throws(()=>validateFixtureTextRegion(bad,'viewport'));
 }
 for(const key of ['lastContent','lastStatusVisibleGlyphs']){
  const bad=structuredClone(entry);bad.geometryBefore[key][0]=1279;bad.geometryAfter=structuredClone(bad.geometryBefore);
  assert.throws(()=>validateTailStatusGeometry(bad),/fit/);
 }
});
test('normalization is fixed and binary OCR retains band clipping and ambiguity rejection',async()=>{
 const path=fileURLToPath(new URL(webkitSources[0].fixture,fixtureRoot));
 await assert.rejects(()=>prepareVerifiedRegionForOcr(path,'unused.png',{left:0,top:0,width:10,height:10},{width:640,height:800},{normalization:'adaptive'}),/fixed region/);
 const size={width:2560,height:1600},processed={width:5832,height:312};
 for(const words of [
  [{text:'Chat',left:12,top:100,width:174,height:66},{text:'Console',left:684,top:100,width:312,height:66}],
  [{text:'Chat',left:210,top:120,width:174,height:66},{text:'Console',left:684,top:120,width:312,height:66},{text:'Console',left:1300,top:120,width:312,height:66}],
 ])assert.throws(()=>conversationTabsFromOcr(rebaseNavigationOcr(tsv(words),size,viewport,processed),size,viewport),/completely inside|Ambiguous/);
 assert.equal(conversationTabsFromOcr(rebaseNavigationOcr(tsv([]),size,viewport,processed),size,viewport),null);
});

test('actual pixel mutations fail after binary OCR, including a correctly sized unreadable viewport',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'robrix-binary-pixel-negatives-'));
 const run=promisify(execFile);
 const unreadable=fileURLToPath(new URL('unreadable-e51a1d0f.png',fixtureRoot));
 const source=fileURLToPath(new URL(webkitSources[0].fixture,fixtureRoot));
 const sourceBytes=await readFile(source),unreadableBytes=await readFile(unreadable);
 assert.equal(createHash('sha256').update(sourceBytes).digest('hex'),webkitSources[0].sha256);
 try{
  // These are explicitly synthetic negative mutations of retained real pixels,
  // not new CI captures. Originals remain immutable and retain their provenance.
  await run('python3',['-c',String.raw`
from PIL import Image
from pathlib import Path
import sys,json,hashlib
source,unreadable,destination=map(Path,sys.argv[1:])
out=destination
with Image.open(unreadable) as image:
    assert image.size==(1280,804)
    image.crop((0,0,1280,800)).save(out/'unreadable-sized.png')
with Image.open(source) as image:
    assert image.size==(1280,1600)
    button=image.crop((400,196,560,276))
    clipped=image.copy()
    clipped.paste(image.getpixel((600,300)),(400,196,560,276))
    clipped.paste(button,(400,146))
    clipped.save(out/'clipped-console.png')
    ambiguous=image.copy()
    ambiguous.paste(button,(900,196))
    ambiguous.save(out/'ambiguous-console.png')
(out/'synthetic-provenance.json').write_text(json.dumps({
    'kind':'synthetic-negative-mutations-not-CI-evidence',
    'sourcePngSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'unreadableSourcePngSha256':hashlib.sha256(unreadable.read_bytes()).hexdigest(),
    'mutations':{'unreadable-sized':'remove bottom four rows only',
                 'clipped-console':'move original button upward 50 source pixels across navigation crop',
                 'ambiguous-console':'duplicate original button within navigation row'}
}))
`,source,unreadable,directory]);
  const sized=join(directory,'unreadable-sized.png');
  await assert.rejects(()=>screenshotConversationTabs(sized,{width:1280,height:800},{recordOcr:true}),/must be readable/);
  // Existence proves that the dimension-valid negative reached both binary
  // OCR modes instead of failing at the earlier full-viewport assertion.
  for(const mode of ['11','6'])await readFile(sized.replace(/\.png$/,`-navigation-binary-psm${mode}-ocr.txt`));
  for(const [name,error] of [['clipped-console',/completely inside|crop edge|must be readable/],['ambiguous-console',/Ambiguous/]]){
   const path=join(directory,name+'.png'),output=join(directory,name+'-binary.png');
   const input=await prepareVerifiedRegionForOcr(path,output,{left:0,top:88,width:640,height:60},{width:640,height:800},{normalization:'navigation-binary'});
   for(const mode of ['11','6']){
    const {stdout}=await run('tesseract',[output,'stdout','-l','eng','--psm',mode,'tsv'],{env:{...process.env,OMP_THREAD_LIMIT:'1'}});
    assert.throws(()=>{
     const rebased=rebaseNavigationOcr(stdout,input.imageSize,input.viewport,input.processedSize);
     assert.ok(conversationTabsFromOcr(rebased,input.imageSize,input.viewport),'Actual pair must be readable');
    },error);
   }
  }
  assert.deepEqual(await readFile(source),sourceBytes);
  assert.deepEqual(await readFile(unreadable),unreadableBytes);
 }finally{await rm(directory,{recursive:true,force:true});}
});
