import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {readScreenshotText,requireChatText,screenshotWordCenter,prepareScreenshotForOcr} from '../tools/verify-robrix-pixels.mjs';
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
 }finally{await rm(directory,{recursive:true,force:true});}
});
