import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {readScreenshotText,requireChatText,screenshotWordCenter,prepareScreenshotForOcr,prepareObservedControlForOcr,conversationTabsFromOcr,screenshotConversationTabs} from '../tools/verify-robrix-pixels.mjs';
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
