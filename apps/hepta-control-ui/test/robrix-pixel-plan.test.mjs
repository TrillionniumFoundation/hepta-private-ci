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
  assert.deepEqual(result,[{check:'exact-theme',passed:false,expected:'Aurora'},{check:'exact-cjk',passed:false}]);
  await assert.rejects(()=>verifyCapture(root,{...entry,pngSha256:'0'.repeat(64)},expected),/bytes changed/);
 }finally{await rm(root,{recursive:true,force:true});}
});
