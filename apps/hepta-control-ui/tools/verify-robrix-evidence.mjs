// Mandatory static-pixel gate, separate from the unchanged browser interaction budget.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {captureSchedule,expectedPixelChecks} from './robrix-pixel-plan.mjs';
import {readScreenshotText,requireChatText,prepareScreenshotForOcr,prepareObservedControlForOcr,prepareObservedFixtureRows,prepareObservedAreaForOcr} from './verify-robrix-pixels.mjs';
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
 const ocrPath=join(directory,expected.name+'-ocr.txt');
 const original=entry.ocrSha256?await readFile(ocrPath,'utf8'):await readScreenshotText(path);
 if(entry.ocrSha256)assert.equal(sha(original),entry.ocrSha256,'Original OCR evidence changed');
 else await writeFile(ocrPath,original);
 await writeFile(join(directory,expected.name+'-pixel-input.json'),JSON.stringify({sourcePngSha256:entry.pngSha256,originalOcrSha256:sha(original)}));
 const outcomes=[];
 let blockText;
 const withBlock=async()=>{
  if(blockText===undefined){blockText=await readScreenshotText(path,{layout:'block'});await writeFile(join(directory,expected.name+'-block-ocr.txt'),blockText);}
  return original+'\n'+blockText;
 };
 if(expected.consoleView){
  const text=/Console/i.test(original)&&/composed|composition/i.test(original)?original:await withBlock();
  outcomes.push({check:'console-label',passed:/Console/i.test(text)},{check:'console-unavailable-reason',passed:/composed|composition/i.test(text)});
 }else{
  let readable=true;try{requireChatText(original,{fixtures:expected.fixtures});}catch{try{requireChatText(await withBlock(),{fixtures:expected.fixtures});}catch{readable=false;}}
  outcomes.push({check:'chat-readability',passed:readable});
  if(expected.fixtures){
   const ordinals=[...original.matchAll(/Fixture\s*(\d{1,3})\b/gi)].map(match=>Number(match[1]));
   outcomes.push({check:'visible-message-count',passed:ordinals.length>=2},{check:'owner-message-order',passed:JSON.stringify(ordinals)===JSON.stringify([...ordinals].sort((a,b)=>a-b))});
  }
 }
 if(expected.draft)outcomes.push({check:'draft-visible',passed:/Theme round trip draft/i.test(original)||/Theme round trip draft/i.test(await withBlock())});
 if(expected.kept)outcomes.push({check:'focus-kept-text',passed:/kept/i.test(original)||/kept/i.test(await withBlock())});
 if(expected.lastMessage)outcomes.push({check:'last-owner-message-visible',passed:/Fixture\s*64/i.test(original)||/Fixture\s*64/i.test(await withBlock())});
 if(expected.jump){
  assert.deepEqual(entry.jumpArea,entry.jumpAreaBefore,'Rendered target moved during capture');
  assert.ok(entry.jumpArea,'Jump requires actual rendered geometry');
  const regionPath=join(directory,expected.name+'-jump-region.png');
  const region=await prepareObservedAreaForOcr(path,regionPath,entry.jumpArea,expected.viewport);
  await writeFile(join(directory,expected.name+'-jump-region.json'),JSON.stringify(region));
  const raw=await readScreenshotText(region.rawPath,{layout:'block'});
  await writeFile(region.rawPath.replace(/\.png$/,'-ocr.txt'),raw);
  let text=raw;
  if(!/Jump to latest/i.test(text)){const normalized=await readScreenshotText(regionPath,{layout:'block'});await writeFile(regionPath.replace(/\.png$/,'-ocr.txt'),normalized);text+='\n'+normalized;}
  outcomes.push({check:'jump-visible-in-rendered-area',passed:/Jump to latest/i.test(text)});
 }
 if(expected.assertTheme){
  let text=original;
  if(!text.toLowerCase().includes(expected.theme.toLowerCase())){
   text=await withBlock();
  }
  if(!text.toLowerCase().includes(expected.theme.toLowerCase())&&entry.observedThemePoint){
   const regionPath=join(directory,expected.name+'-theme-region.png');
   const region=await prepareObservedControlForOcr(path,regionPath,entry.observedThemePoint,expected.viewport);
   await writeFile(join(directory,expected.name+'-theme-region.json'),JSON.stringify(region));
   const raw=await readScreenshotText(region.rawPath,{layout:'block'});
   await writeFile(region.rawPath.replace(/\.png$/,'-ocr.txt'),raw);text+='\n'+raw;
   if(!text.toLowerCase().includes(expected.theme.toLowerCase())){
    const regionText=await readScreenshotText(regionPath,{layout:'block'});
    await writeFile(join(directory,expected.name+'-theme-region-ocr.txt'),regionText);text+='\n'+regionText;
   }
   if(!text.toLowerCase().includes(expected.theme.toLowerCase())&&region.textRawPath){
    for(const input of [region.textRawPath,region.textPath]){
     const line=await readScreenshotText(input,{layout:'block'});
     await writeFile(input.replace(/\.png$/,'-ocr.txt'),line);text+='\n'+line;
    }
   }
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
   if(!/中文输入|键盘焦点|滚动位置/.test(text.replace(/\s+/g,''))){
    const regions=await prepareObservedFixtureRows(path,normalized,join(directory,expected.name),expected.viewport.width);
    for(const region of regions){
     const rowText=await readScreenshotText(region.path,{language:'eng+chi_sim',layout:'block'});
     await writeFile(region.path.replace(/\.png$/,'-ocr.txt'),rowText);text+='\n'+rowText;
    }
   }
  }
  outcomes.push({check:'exact-cjk',passed:/中文输入|键盘焦点|滚动位置/.test(text.replace(/\s+/g,''))});
 }
 assert.deepEqual(outcomes.map(item=>item.check),expectedPixelChecks(expected),'Every planned semantic assertion must run');
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
      assert.deepEqual(origin.viewport,item.viewport);
      assert.equal(origin.theme,'Aurora','Theme locator must come from the observed initial Aurora control');
      assert.equal(sha(await readFile(join(directory,origin.name+'.png'))),origin.pngSha256,'Theme locator source screenshot changed');
      assert.equal(origin.pngSha256,entry.observedThemePoint.sourcePngSha256);
     }
     const checks=await verifyCapture(directory,entry,item);
     results.push({...subject,name:item.name,checks,passed:checks.every(check=>check.passed)});
    }catch(error){results.push({...subject,name:item.name,passed:false,error:String(error)});}
   }
  }catch(error){results.push({...subject,passed:false,error:String(error)});}
 }
 const required=[1280,640].flatMap(width=>captureSchedule(width,fixtures));
 const assertions=results.flatMap(result=>result.checks??[]);
 return {schema:'hepta.robrix-pixel-check.v1',sourceSha,fixtures,captures:{required:required.length*3,passed:results.filter(result=>result.name&&result.passed).length},semanticChecks:{required:required.reduce((count,item)=>count+expectedPixelChecks(item).length,0)*3,evaluated:assertions.length,passed:assertions.filter(item=>item.passed).length},results,passed:results.every(result=>result.passed)};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const [root,scope]=process.argv.slice(2);assert.ok(['default','fixtures'].includes(scope));
 const result=await verifyEvidence(root,process.env.SOURCE_SHA,scope==='fixtures');
 await writeFile(join(root,'..',`robrix-${scope}-pixel-results.json`),JSON.stringify(result,null,2)+'\n');
 for(const failure of result.results.filter(item=>!item.passed))console.error(JSON.stringify(failure));
 console.log(`Capture records: ${result.captures.passed}/${result.captures.required}; semantic checks: ${result.semanticChecks.passed} passed, ${result.semanticChecks.evaluated} evaluated, ${result.semanticChecks.required} required`);
 if(!result.passed)process.exitCode=1;
}
