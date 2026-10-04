// QA tooling only. Reads actual host screenshots; never supplies UI text.
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdtemp,rm} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
const run=promisify(execFile);
export async function prepareScreenshotForOcr(path,output){
 await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,output],{timeout:20000,maxBuffer:65536});
 return output;
}
export async function prepareObservedControlForOcr(path,output,point,viewport){
 const bytes=await readFile(path);
 assert.equal(bytes.subarray(1,4).toString(),'PNG');
 const width=bytes.readUInt32BE(16),height=bytes.readUInt32BE(20),scale=width/viewport.width;
 assert.equal(height,Math.round(viewport.height*scale),'Control ROI requires a verified full-viewport capture');
 assert.ok(Number.isFinite(point.x)&&Number.isFinite(point.y)&&point.x>0&&point.x<viewport.width&&point.y>0&&point.y<viewport.height,'Control must have been observed inside this viewport');
 // Fixed text-centered region around the real first-theme OCR observation.
 // It is not a claimed widget rectangle; full-frame visibility checks remain.
 const left=Math.max(0,Math.floor((point.x-80)*scale));
 const top=Math.max(0,Math.floor((point.y-28)*scale));
 const region={left,top,width:Math.min(width-left,Math.ceil(280*scale)),height:Math.min(height-top,Math.ceil(56*scale)),observedPoint:point,viewport};
 await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,output,...[region.left,region.top,region.width,region.height].map(String)],{timeout:20000,maxBuffer:65536});
 const rawPath=output.replace(/\.png$/,'-raw.png');
 await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,rawPath,...[region.left,region.top,region.width,region.height].map(String),'--raw'],{timeout:20000,maxBuffer:65536});
 const result={...region,rawPath};
 if(point.textBounds){
  const bounds=point.textBounds;
  assert.ok([bounds.left,bounds.top,bounds.width,bounds.height].every(Number.isFinite)&&bounds.width>0&&bounds.height>0,'Observed text bounds must be finite and positive');
  assert.ok(bounds.left>=0&&bounds.top>=0&&bounds.left+bounds.width<=viewport.width&&bounds.top+bounds.height<=viewport.height,'Observed text bounds must be within this viewport');
  assert.ok(point.x>=bounds.left&&point.x<=bounds.left+bounds.width&&point.y>=bounds.top&&point.y<=bounds.top+bounds.height,'Observed center must belong to the recorded glyph bounds');
  const textRegion={left:region.left,top:Math.max(0,Math.floor((bounds.top-4)*scale)),width:region.width,height:Math.ceil((bounds.height+8)*scale)};
  assert.ok(textRegion.top+textRegion.height<=height,'Observed text line must remain within the screenshot');
  const textPath=output.replace(/\.png$/,'-text-line.png'),textRawPath=output.replace(/\.png$/,'-text-line-raw.png');
  const args=[textRegion.left,textRegion.top,textRegion.width,textRegion.height].map(String);
  await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,textPath,...args],{timeout:20000,maxBuffer:65536});
  await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,textRawPath,...args,'--raw'],{timeout:20000,maxBuffer:65536});
  Object.assign(result,{textRegion,textPath,textRawPath});
 }
 return result;
}
export async function prepareObservedFixtureRows(path,normalized,prefix,viewportWidth){
 const original=await readFile(path),processed=await readFile(normalized);
 const width=original.readUInt32BE(16),height=original.readUInt32BE(20);
 const scale=processed.readUInt32BE(16)/width,cssScale=width/viewportWidth;
 assert.equal(scale,3,'Row observation must use the fixed normalization');
 const {stdout,stderr}=await run('tesseract',[normalized,'stdout','-l','eng','--psm','11','tsv'],{env:{...process.env,OMP_THREAD_LIMIT:'1'},timeout:20000,maxBuffer:256*1024});
 assert.doesNotMatch(stderr,/Failed loading language|Error opening data file|Can't open tsv/i);
 await writeFile(prefix+'-row-observations.tsv',stdout);
 const lines=new Map();
 for(const line of stdout.trim().split('\n').slice(1)){
  const cells=line.split('\t');if(cells.length<12||cells[0]!=='5')continue;
  const key=cells.slice(1,5).join(':');const words=lines.get(key)??[];words.push(cells);lines.set(key,words);
 }
 const regions=[];
 for(const words of lines.values()){
  const text=words.map(cells=>cells[11]).join(' '),match=text.match(/\bFixture\s*(\d{1,2})\b/);
  if(!match)continue;
  const ordinal=Number(match[1]);
  // These are the CJK-bearing messages of the explicit 64-row owner fixture.
  if(ordinal<3||ordinal>63||ordinal%4!==3||regions.some(row=>row.ordinal===ordinal))continue;
  const x=Math.min(...words.map(c=>Number(c[6]))),y=Math.min(...words.map(c=>Number(c[7])));
  const bottom=Math.max(...words.map(c=>Number(c[7])+Number(c[9])));
  const left=Math.max(0,Math.floor(x/scale-4*cssScale)),top=Math.max(0,Math.floor(y/scale-8*cssScale));
  const region={ordinal,observedText:text,left,top,width:Math.min(width-left,Math.ceil(800*cssScale)),height:Math.min(height-top,Math.ceil((bottom-y)/scale+16*cssScale))};
  assert.ok([region.left,region.top,region.width,region.height].every(Number.isFinite));
  const output=prefix+`-cjk-row-${ordinal}.png`;
  await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,output,...[region.left,region.top,region.width,region.height].map(String)],{timeout:20000,maxBuffer:65536});
  regions.push({...region,path:output});
  if(regions.length===2)break;
 }
 await writeFile(prefix+'-cjk-regions.json',JSON.stringify(regions,null,2));
 return regions;
}
export async function prepareObservedAreaForOcr(path,output,area,viewport){
 const bytes=await readFile(path),scale=bytes.readUInt32BE(16)/viewport.width;
 assert.equal(bytes.readUInt32BE(20),Math.round(viewport.height*scale));
 assert.ok([area.x,area.y,area.width,area.height].every(Number.isFinite));
 assert.ok(area.x>=0&&area.y>=0&&area.width>0&&area.height>0&&area.x+area.width<=viewport.width&&area.y+area.height<=viewport.height,'Rendered area must be visible and inside the viewport');
 const region={left:Math.floor(area.x*scale),top:Math.floor(area.y*scale),width:Math.ceil(area.width*scale),height:Math.ceil(area.height*scale),observedArea:area};
 const args=[region.left,region.top,region.width,region.height].map(String);
 await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,output,...args],{timeout:20000,maxBuffer:65536});
 const rawPath=output.replace(/\.png$/,'-raw.png');
 await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,rawPath,...args,'--raw'],{timeout:20000,maxBuffer:65536});
 return {...region,rawPath};
}
export async function readScreenshotText(path,{language='eng',layout='sparse'}={}){
 assert.ok(['eng','eng+chi_sim'].includes(language),'Only pinned QA OCR languages are accepted');
 assert.ok(['sparse','block'].includes(layout),'Only fixed QA layout modes are accepted');
 const {stdout,stderr}=await run('tesseract',[path,'stdout','-l',language,'--psm',layout==='block'?'6':'11'],{env:{...process.env,OMP_THREAD_LIMIT:'1'},timeout:20000,maxBuffer:65536});
 assert.doesNotMatch(stderr,/Failed loading language|Error opening data file|couldn't load any languages/i,'OCR must not silently fall back when a requested language is missing');
 return stdout;
}
export async function screenshotWordCenter(path,word,viewportWidth,{topOnly=false,recordOcr=false}={}){
 const bytes=await readFile(path);
 assert.equal(bytes.subarray(1,4).toString(),'PNG');
 const ratio=bytes.readUInt32BE(16)/viewportWidth;
 let row;
 for(const mode of ['11','6']){
  const {stdout}=await run('tesseract',[path,'stdout','-l','eng','--psm',mode,'tsv'],{env:{...process.env,OMP_THREAD_LIMIT:'1'},timeout:20000,maxBuffer:256*1024});
  if(recordOcr)await writeFile(path.replace(/\.png$/,`-controls-psm${mode}-ocr.txt`),stdout);
  const rows=stdout.trim().split('\n').slice(1).map(line=>line.split('\t'));
  row=rows.find(c=>c.length>=12&&c[11].toLowerCase()===word.toLowerCase()&&(!topOnly||Number(c[7])/ratio<90));
  if(row)break;
 }
 assert.ok(row,`Actual rendered control ${word} must be readable before activation`);
 return{x:(Number(row[6])+Number(row[8])/2)/ratio,y:(Number(row[7])+Number(row[9])/2)/ratio,textBounds:{left:Number(row[6])/ratio,top:Number(row[7])/ratio,width:Number(row[8])/ratio,height:Number(row[9])/ratio}};
}
// Expected Aurora navigation bands for the two actual browser test viewports.
// The theme cycle returns to Aurora before either tab is activated.
// Rust source: home.rs brand heights 68/44, rail 64 and mobile row padding 6;
// visual_theme.rs Aurora sidebar 248 and heading 92; room.rs compact heading 48;
// home.rs Dock tabs 44; styles.rs AuroraButton height 40.
// These are layout assertions, never fallback click coordinates. A deliberate
// layout/viewport change must update this contract and its real-pixel fixtures.
export function conversationNavigationRegion(viewport){
 assert.equal(viewport.height,800,'Navigation OCR requires an explicitly covered viewport');
 assert.ok([640,1280].includes(viewport.width),'Navigation OCR requires an explicitly covered viewport');
 return viewport.width===1280
  ? {left:64+248,top:68+92,width:viewport.width-64-248,height:44}
  : {left:0,top:44+48,width:viewport.width,height:40+6+6};
}
function navigationOcrContext(viewport){
 const band=conversationNavigationRegion(viewport),padding=4;
 // Preserve a fixed context outside the acceptance band so OCR can observe
 // glyphs that cross its edge. The accepted navigation band never expands.
 const left=Math.max(0,band.left-padding),top=Math.max(0,band.top-padding);
 return {left,top,width:Math.min(viewport.width,band.left+band.width+padding)-left,height:Math.min(viewport.height,band.top+band.height+padding)-top};
}
export function conversationTabsFromOcr(tsv,imageSize,viewport){
 const region=conversationNavigationRegion(viewport);
 assert.ok(Number.isInteger(imageSize.width)&&imageSize.width>0&&Number.isInteger(imageSize.height)&&imageSize.height>0,'Screenshot dimensions must be positive integers');
 const ratio=imageSize.width/viewport.width;
 assert.equal(imageSize.height,Math.round(viewport.height*ratio),'Navigation OCR requires a verified full-viewport capture');
 const words={chat:[],console:[]};
 for(const line of tsv.trim().split('\n').slice(1)){
  const c=line.split('\t');
  if(c.length<12||c[0]!=='5')continue;
  const name=c[11].toLowerCase();if(!Object.hasOwn(words,name))continue;
  const [left,top,width,height]=c.slice(6,10).map(value=>Number(value)/ratio);
  assert.ok([left,top,width,height].every(Number.isFinite)&&width>0&&height>0,'Observed navigation glyph bounds must be finite and positive');
  const right=left+width,bottom=top+height;
  const intersects=left<region.left+region.width&&right>region.left&&top<region.top+region.height&&bottom>region.top;
  if(!intersects)continue;
  assert.ok(left>=region.left&&top>=region.top&&right<=region.left+region.width&&bottom<=region.top+region.height,'Navigation labels must be completely inside the expected visible tab band');
  words[name].push({x:left+width/2,y:top+height/2,textBounds:{left,top,width,height}});
 }
 assert.ok(words.chat.length<=1&&words.console.length<=1,'Ambiguous Chat/Console navigation labels must not be activated');
 if(words.chat.length!==1||words.console.length!==1)return null;
 const [chat,console]=[words.chat[0],words.console[0]];
 const a=chat.textBounds,b=console.textBounds;
 const overlap=Math.min(a.top+a.height,b.top+b.height)-Math.max(a.top,b.top);
 assert.ok(a.left+a.width<=b.left&&overlap>=Math.min(a.height,b.height)/2,'Chat and Console must form one left-to-right rendered navigation row');
 return {Chat:chat,Console:console,region};
}
export function sourcePixelRegion(area,viewport,imageSize){
 assert.ok([viewport.width,viewport.height,imageSize.width,imageSize.height].every(value=>Number.isInteger(value)&&value>0),'Source and viewport dimensions must be positive integers');
 const scale=imageSize.width/viewport.width;
 assert.equal(imageSize.height,Math.round(viewport.height*scale),'Region OCR requires a verified full-viewport capture');
 assert.ok([area.left,area.top,area.width,area.height].every(Number.isFinite)&&area.width>0&&area.height>0,'Region geometry must be finite and positive');
 assert.ok(area.left>=0&&area.top>=0&&area.left+area.width<=viewport.width&&area.top+area.height<=viewport.height,'Region must be completely inside the real viewport');
 const left=Math.floor(area.left*scale),top=Math.floor(area.top*scale);
 const right=Math.ceil((area.left+area.width)*scale),bottom=Math.ceil((area.top+area.height)*scale);
 assert.ok(right<=imageSize.width&&bottom<=imageSize.height&&right>left&&bottom>top,'Pixel crop must remain inside the source PNG');
 return {left,top,width:right-left,height:bottom-top};
}
export async function prepareVerifiedRegionForOcr(path,output,area,viewport){
 const bytes=await readFile(path);assert.equal(bytes.subarray(1,4).toString(),'PNG');
 const imageSize={width:bytes.readUInt32BE(16),height:bytes.readUInt32BE(20)};
 const crop=sourcePixelRegion(area,viewport,imageSize);
 await run('python3',[fileURLToPath(new URL('./prepare-ocr-pixels.py',import.meta.url)),path,output,...[crop.left,crop.top,crop.width,crop.height].map(String)],{timeout:20000,maxBuffer:65536});
 assert.deepEqual(await readFile(path),bytes,'Original PNG changed during fixed region processing');
 const processed=await readFile(output);
 assert.equal(processed.subarray(1,4).toString(),'PNG');
 const processedSize={width:processed.readUInt32BE(16),height:processed.readUInt32BE(20)};
 assert.deepEqual(processedSize,{width:crop.width*3,height:crop.height*3},'Region OCR must use the existing fixed three-times normalization');
 return {sourcePngSha256:createHash('sha256').update(bytes).digest('hex'),imageSize,processedSize,crop,area,viewport,normalizationScale:3};
}
export function rebaseNavigationOcr(tsv,imageSize,viewport,processedSize){
 const crop=sourcePixelRegion(navigationOcrContext(viewport),viewport,imageSize);
 assert.deepEqual(processedSize,{width:crop.width*3,height:crop.height*3},'Navigation OCR dimensions must match the fixed source crop');
 return tsv.split('\n').map((line,index)=>{
  const c=line.split('\t');if(index===0||c.length<12||c[0]!=='5'||!c[11].trim())return line;
  const [x,y,w,h]=c.slice(6,10).map(Number);
  assert.ok([x,y,w,h].every(Number.isFinite)&&x>=0&&y>=0&&w>0&&h>0&&x+w<=processedSize.width&&y+h<=processedSize.height,'OCR glyph bounds must belong to the actual processed region');
  if(['chat','console'].includes(c[11].toLowerCase()))assert.ok(x>0&&y>0&&x+w<processedSize.width&&y+h<processedSize.height,'Navigation glyph touching the OCR crop edge cannot prove complete visibility');
  c.splice(6,4,String(crop.left+x/3),String(crop.top+y/3),String(w/3),String(h/3));
  return c.join('\t');
 }).join('\n');
}
export async function screenshotConversationTabs(path,viewport,{recordOcr=false}={}){
 const temporary=recordOcr?null:await mkdtemp(join(tmpdir(),'robrix-navigation-ocr-'));
 const normalized=recordOcr?path.replace(/\.png$/,'-navigation-normalized.png'):join(temporary,'navigation.png');
 try{
  const input=await prepareVerifiedRegionForOcr(path,normalized,navigationOcrContext(viewport),viewport);
  for(const mode of ['11','6']){
   const {stdout,stderr}=await run('tesseract',[normalized,'stdout','-l','eng','--psm',mode,'tsv'],{env:{...process.env,OMP_THREAD_LIMIT:'1'},timeout:20000,maxBuffer:256*1024});
   assert.doesNotMatch(stderr,/Failed loading language|Error opening data file|Can't open tsv/i);
   const rebased=rebaseNavigationOcr(stdout,input.imageSize,viewport,input.processedSize);
   if(recordOcr){
    await writeFile(path.replace(/\.png$/,`-navigation-psm${mode}-ocr.txt`),stdout);
    await writeFile(path.replace(/\.png$/,`-navigation-psm${mode}-source-coordinates.tsv`),rebased);
   }
   // Only a missing exact label may try the other existing OCR layout mode.
   // Ambiguity, clipping or a broken row fails immediately, never by confidence.
   const observed=conversationTabsFromOcr(rebased,input.imageSize,viewport);
   if(observed){
    const result={...observed,...input,ocrMode:mode};
    if(recordOcr)await writeFile(path.replace(/\.png$/,'-navigation-controls.json'),JSON.stringify(result,null,2));
    return result;
   }
  }
  assert.fail('Actual rendered Chat/Console pair must be readable inside the navigation band before activation');
 }finally{
  if(temporary)await rm(temporary,{recursive:true,force:true});
 }
}
export function requireChatText(text,{fixtures=false}={}){
 assert.match(text,/\bconversations?\b/i,'Actual canvas screenshot must contain readable conversation navigation');
 assert.match(text,fixtures?/\bfixture\b/i:/\bdraft\b/i,'Actual canvas screenshot must contain its truthful draft/fixture state');
}
