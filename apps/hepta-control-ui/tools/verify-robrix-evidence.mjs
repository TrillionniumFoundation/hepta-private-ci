// Mandatory static-pixel gate, separate from the unchanged browser interaction budget.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {captureSchedule,expectedPixelChecks} from './robrix-pixel-plan.mjs';
import {readScreenshotText,requireChatText,prepareScreenshotForOcr,prepareObservedControlForOcr,prepareObservedFixtureRows,prepareObservedAreaForOcr,prepareVerifiedRegionForOcr} from './verify-robrix-pixels.mjs';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export function validateFixtureTextRegion(entry,kind){
 assert.ok(['viewport','composer'].includes(kind),'Unknown fixture text region');
 assert.ok(entry.viewport&&[entry.viewport.width,entry.viewport.height].every(value=>Number.isInteger(value)&&value>0),'Actual capture viewport is required');
 const g=entry.geometryBefore;
 assert.ok(g&&g.layoutFinalized===true&&Number.isInteger(g.frame)&&g.frame>0,'Region OCR requires finalized actual Rust draw geometry');
 assert.deepEqual(g,entry.geometryAfter,'Region geometry changed during the actual capture');
 assert.ok(Number.isInteger(g.total)&&g.total>0,'Region geometry requires its rendered message population');
 const checked=name=>{
  const rect=g[name];assert.ok(Array.isArray(rect)&&rect.length===4&&rect.every(Number.isFinite),'Rendered region must contain four finite coordinates');
  const [left,top,width,height]=rect;
  assert.ok(width>0&&height>0&&left>=0&&top>=0&&left+width<=entry.viewport.width&&top+height<=entry.viewport.height,'Rendered region must be positive and wholly inside the actual viewport');
  return {left,top,width,height};
 };
 const timeline=checked('viewport'),composer=checked('composer');
 assert.ok(timeline.top+timeline.height<=composer.top&&composer.left>=timeline.left&&composer.left+composer.width<=timeline.left+timeline.width,'Timeline and composer regions must be separate and belong to the same visible pane');
 return kind==='viewport'?timeline:composer;
}
export function fixtureMessageObservation(text,total){
 // One independent OCR result only: never concatenate passes to count a
 // single visible message twice. Duplicate ordinals do not add messages.
 assert.equal(typeof text,'string','Message observation accepts one independent OCR string');
 assert.ok(Number.isInteger(total)&&total>0,'Message observation requires the actual rendered population');
 const ordinals=[];let tokensValid=true;
 // Read the complete token, including malformed decimals or oversized values.
 // A bad later marker invalidates the observation; it cannot disappear through
 // a three-digit regex cap or contribute only its numeric prefix.
 for(const marker of text.matchAll(/(?<![\p{L}\p{N}_])Fixture(?![\p{L}_])/giu)){
  const tail=text.slice(marker.index+marker[0].length);
  const token=tail.match(/^\s*([^\s\]\)}]*)/u)?.[1]??'';
  if(!/^[1-9][0-9]*$/.test(token)){tokensValid=false;continue;}
  const value=Number(token);
  if(!Number.isSafeInteger(value)){tokensValid=false;continue;}
  ordinals.push(value);
 }
 const count=new Set(ordinals).size;
 const populationMatches=ordinals.every(value=>value>=1&&value<=total);
 return {ordinals,count,countPassed:tokensValid&&populationMatches&&count>=2,orderPassed:tokensValid&&populationMatches&&count>=2&&JSON.stringify(ordinals)===JSON.stringify([...ordinals].sort((a,b)=>a-b))};
}
export function validateTailStatusGeometry(entry){
 const g=entry.geometryBefore;
 assert.ok(g,'Follow-latest capture requires real Rust geometry');
 assert.deepEqual(g,entry.geometryAfter,'Tail geometry changed during capture');
 assert.equal(g.layoutFinalized,true,'Tail geometry must be sampled after Root layout');
 assert.equal(g.followLatest,true,'Expected retained follow-latest intent');
 assert.equal(g.atEnd,true,'Rendered PortalList must have reached its end');
 assert.equal(g.total,64,'Status must belong to the actual final fixture row');
 const valid=rect=>Array.isArray(rect)&&rect.length===4&&rect.every(Number.isFinite)&&rect[2]>0&&rect[3]>0;
 for(const key of ['viewport','lastRow','lastContent','lastStatusVisibleGlyphs','composer'])assert.ok(valid(g[key]),`Missing/invalid actual ${key} bounds`);
 const [vx,vy,vw,vh]=g.viewport,[rx,ry,rw,rh]=g.lastRow,[x,y,width,height]=g.lastStatusVisibleGlyphs;
 const epsilon=0.01; // Float-coordinate roundoff only, not a pixel clipping allowance.
 // Raster-aligned SDK layout bounds can extend fractionally beyond the CSS
 // canvas. Check content against the actually visible intersection, never
 // increase a tolerance or clip an overflowing message/status into a pass.
 const left=Math.max(0,vx),top=Math.max(0,vy),right=Math.min(entry.viewport.width,vx+vw),bottom=Math.min(entry.viewport.height,vy+vh);
 assert.ok(right>left&&bottom>top,'Timeline has no visible screenshot intersection');
 assert.ok(ry>=top-epsilon&&ry+rh<=bottom+epsilon,'Entire final fixture row height must fit visible timeline');
 const [cx,cy,cw,ch]=g.lastContent;
 assert.ok(cx>=left-epsilon&&cy>=top-epsilon&&cx+cw<=right+epsilon&&cy+ch<=bottom+epsilon,'Entire final message content must fit visible timeline');
 assert.ok(x>=Math.max(left,rx)-epsilon&&y>=Math.max(top,ry)-epsilon&&x+width<=Math.min(right,rx+rw)+epsilon&&y+height<=Math.min(bottom,ry+rh)+epsilon,'All status glyph bounds must fit final row and visible timeline');
 assert.ok(y+height<=g.composer[1]+epsilon,'Composer must not cover final status');
 return {x:Math.max(left,x-4),y:Math.max(top,y-4),width:Math.min(right,x+width+4)-Math.max(left,x-4),height:Math.min(bottom,y+height+4)-Math.max(top,y-4)};
}
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
 const regionTexts=new Map();
 const withFixtureRegion=async kind=>{
  assert.equal(expected.fixtures,true,'Only actual fixture draw observations can define these regions');
  if(!regionTexts.has(kind)){
   const area=validateFixtureTextRegion(entry,kind);
   const regionPath=join(directory,expected.name+`-${kind}-readability-region.png`);
   const input=await prepareVerifiedRegionForOcr(path,regionPath,area,expected.viewport);
   assert.equal(input.sourcePngSha256,entry.pngSha256,'Region must come from the exact captured PNG');
   const text=await readScreenshotText(regionPath,{layout:'block'});
   await writeFile(regionPath.replace(/\.png$/,'-ocr.txt'),text);
   await writeFile(regionPath.replace(/\.png$/,'.json'),JSON.stringify({...input,geometry:entry.geometryBefore,ocrSha256:sha(text)}));
   regionTexts.set(kind,text);
  }
  return regionTexts.get(kind);
 };
 if(expected.consoleView){
  const text=/Console/i.test(original)&&/composed|composition/i.test(original)?original:await withBlock();
  outcomes.push({check:'console-label',passed:/Console/i.test(text)},{check:'console-unavailable-reason',passed:/composed|composition/i.test(text)});
 }else{
  let readable=true;try{requireChatText(original,{fixtures:expected.fixtures});}catch{try{requireChatText(await withBlock(),{fixtures:expected.fixtures});}catch{readable=false;}}
  outcomes.push({check:'chat-readability',passed:readable});
  if(expected.fixtures){
   const observed=fixtureMessageObservation(await withFixtureRegion('viewport'),entry.geometryBefore.total);
   outcomes.push({check:'visible-message-count',passed:observed.countPassed},{check:'owner-message-order',passed:observed.orderPassed});
  }
 }
 if(expected.draft)outcomes.push({check:'draft-visible',passed:expected.fixtures?/Theme round trip draft/i.test(await withFixtureRegion('composer')):/Theme round trip draft/i.test(original)||/Theme round trip draft/i.test(await withBlock())});
 if(expected.kept)outcomes.push({check:'focus-kept-text',passed:expected.fixtures?/kept/i.test(await withFixtureRegion('composer')):/kept/i.test(original)||/kept/i.test(await withBlock())});
 if(expected.lastMessage)outcomes.push({check:'last-owner-message-visible',passed:/Fixture\s*64/i.test(original)||/Fixture\s*64/i.test(await withBlock())});
 if(expected.fixtures&&!expected.consoleView&&!expected.jump){
  const area=validateTailStatusGeometry(entry);
  const regionPath=join(directory,expected.name+'-last-status-region.png');
  const region=await prepareObservedAreaForOcr(path,regionPath,area,expected.viewport);
  await writeFile(join(directory,expected.name+'-last-status-region.json'),JSON.stringify({sourcePngSha256:entry.pngSha256,geometry:entry.geometryBefore,visibleTimelineIntersection:{left:Math.max(0,entry.geometryBefore.viewport[0]),top:Math.max(0,entry.geometryBefore.viewport[1]),right:Math.min(entry.viewport.width,entry.geometryBefore.viewport[0]+entry.geometryBefore.viewport[2]),bottom:Math.min(entry.viewport.height,entry.geometryBefore.viewport[1]+entry.geometryBefore.viewport[3])},...region}));
  const raw=await readScreenshotText(region.rawPath,{layout:'block'});
  await writeFile(region.rawPath.replace(/\.png$/,'-ocr.txt'),raw);
  let text=raw;
  if(!/\bReceiving\b/.test(text)){const normalized=await readScreenshotText(regionPath,{layout:'block'});await writeFile(regionPath.replace(/\.png$/,'-ocr.txt'),normalized);text+='\n'+normalized;}
  outcomes.push({check:'last-owner-status-fully-visible',passed:/\bReceiving\b/.test(text)});
 }
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
