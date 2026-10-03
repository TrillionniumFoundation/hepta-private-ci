// QA tooling only. Reads actual host screenshots; never supplies UI text.
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
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
 return region;
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
 return{x:(Number(row[6])+Number(row[8])/2)/ratio,y:(Number(row[7])+Number(row[9])/2)/ratio};
}
export function requireChatText(text,{fixtures=false}={}){
 assert.match(text,/\bconversations?\b/i,'Actual canvas screenshot must contain readable conversation navigation');
 assert.match(text,fixtures?/\bfixture\b/i:/\bdraft\b/i,'Actual canvas screenshot must contain its truthful draft/fixture state');
}
