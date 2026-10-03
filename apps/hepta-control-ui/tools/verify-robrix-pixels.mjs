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
