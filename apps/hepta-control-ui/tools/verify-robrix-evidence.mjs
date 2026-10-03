// Mandatory static-pixel gate, separate from the unchanged browser interaction budget.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {captureSchedule} from './robrix-pixel-plan.mjs';
import {readScreenshotText,prepareScreenshotForOcr,prepareObservedControlForOcr} from './verify-robrix-pixels.mjs';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function verifyCapture(directory,entry,expected){
 assert.equal(entry.name,expected.name);
 assert.equal(entry.theme,expected.theme);
 assert.deepEqual(entry.viewport,expected.viewport);
 const path=join(directory,expected.name+'.png');
 const bytes=await readFile(path);
 assert.equal(sha(bytes),entry.pngSha256,'Original screenshot bytes changed');
 assert.equal(bytes.subarray(1,4).toString(),'PNG');
 const scale=bytes.readUInt32BE(16)/expected.viewport.width;
 assert.equal(bytes.readUInt32BE(20),Math.round(expected.viewport.height*scale),'Full viewport must remain visible');
 const original=await readFile(join(directory,expected.name+'-ocr.txt'),'utf8');
 assert.equal(sha(original),entry.ocrSha256,'Original OCR evidence changed');
 const outcomes=[];
 if(expected.assertTheme){
  let text=original;
  if(!text.toLowerCase().includes(expected.theme.toLowerCase())){
   const block=await readScreenshotText(path,{layout:'block'});
   await writeFile(join(directory,expected.name+'-block-ocr.txt'),block);text+='\n'+block;
  }
  if(!text.toLowerCase().includes(expected.theme.toLowerCase())&&entry.observedThemePoint){
   const regionPath=join(directory,expected.name+'-theme-region.png');
   const region=await prepareObservedControlForOcr(path,regionPath,entry.observedThemePoint,expected.viewport);
   await writeFile(join(directory,expected.name+'-theme-region.json'),JSON.stringify(region));
   const regionText=await readScreenshotText(regionPath,{layout:'block'});
   await writeFile(join(directory,expected.name+'-theme-region-ocr.txt'),regionText);text+='\n'+regionText;
  }
  outcomes.push({check:'exact-theme',passed:text.toLowerCase().includes(expected.theme.toLowerCase()),expected:expected.theme});
 }
 if(expected.cjk){
  let text=await readScreenshotText(path,{language:'eng+chi_sim'});
  await writeFile(join(directory,expected.name+'-cjk-ocr.txt'),text);
  if(!/中文输入|键盘焦点|滚动位置/.test(text.replace(/\s+/g,''))){
   const normalized=await prepareScreenshotForOcr(path,join(directory,expected.name+'-ocr-pixels.png'));
   const additional=await readScreenshotText(normalized,{language:'eng+chi_sim'});
   await writeFile(join(directory,expected.name+'-cjk-normalized-ocr.txt'),additional);text+='\n'+additional;
  }
  outcomes.push({check:'exact-cjk',passed:/中文输入|键盘焦点|滚动位置/.test(text.replace(/\s+/g,''))});
 }
 return outcomes;
}
export async function verifyEvidence(root,sourceSha,fixtures){
 assert.match(sourceSha,/^[0-9a-f]{40}$/);
 const results=[];
 for(const browser of ['chromium','firefox','webkit'])for(const initialWidth of [1280,640]){
  const directory=join(root,`robrix-host-Robrix-host-starts-under-strict-CSP-${initialWidth}-${browser}`);
  const subject={browser,initialWidth};
  try{
   const plan=JSON.parse(await readFile(join(directory,'pixel-plan.json'),'utf8'));
   assert.equal(plan.sourceSha,sourceSha);assert.equal(plan.browser,browser);
   assert.equal(plan.initialWidth,initialWidth);assert.equal(plan.fixtures,fixtures);
   const expected=captureSchedule(initialWidth,fixtures);
   assert.equal(new Set(plan.captures.map(entry=>entry.name)).size,plan.captures.length,'Duplicate capture task');
   assert.ok(plan.captures.every(entry=>expected.some(item=>item.name===entry.name)),'Unexpected capture task');
   for(const item of expected){
    try{
     const entry=plan.captures.find(value=>value.name===item.name);
     assert.ok(entry,`Missing mandatory capture ${item.name}`);
     if(entry.observedThemePoint){
      const origin=plan.captures.find(value=>value.name===entry.observedThemePoint.sourceCapture);
      assert.ok(origin,'Observed control must name an actual capture from this subject');
      assert.equal(origin.viewport.width,item.viewport.width);
      assert.equal(origin.pngSha256,entry.observedThemePoint.sourcePngSha256);
     }
     const checks=await verifyCapture(directory,entry,item);
     results.push({...subject,name:item.name,checks,passed:checks.every(check=>check.passed)});
    }catch(error){results.push({...subject,name:item.name,passed:false,error:String(error)});}
   }
  }catch(error){results.push({...subject,passed:false,error:String(error)});}
 }
 return {schema:'hepta.robrix-pixel-check.v1',sourceSha,fixtures,results,passed:results.every(result=>result.passed)};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const [root,scope]=process.argv.slice(2);assert.ok(['default','fixtures'].includes(scope));
 const result=await verifyEvidence(root,process.env.SOURCE_SHA,scope==='fixtures');
 await writeFile(join(root,'..',`robrix-${scope}-pixel-results.json`),JSON.stringify(result,null,2)+'\n');
 for(const failure of result.results.filter(item=>!item.passed))console.error(JSON.stringify(failure));
 console.log(`Static pixel checks: ${result.results.filter(item=>item.passed).length}/${result.results.length}`);
 if(!result.passed)process.exitCode=1;
}
