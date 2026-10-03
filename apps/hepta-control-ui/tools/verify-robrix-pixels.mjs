// QA tooling only. Reads actual host screenshots; never supplies UI text.
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const run=promisify(execFile);
export async function readScreenshotText(path,{language='eng'}={}){
 assert.ok(['eng','eng+chi_sim'].includes(language),'Only pinned QA OCR languages are accepted');
 const {stdout}=await run('tesseract',[path,'stdout','-l',language,'--psm','11'],{timeout:20000,maxBuffer:65536});
 return stdout;
}
export async function screenshotWordCenter(path,word,viewportWidth,{topOnly=false}={}){
 const bytes=await readFile(path);
 assert.equal(bytes.subarray(1,4).toString(),'PNG');
 const ratio=bytes.readUInt32BE(16)/viewportWidth;
 const {stdout}=await run('tesseract',[path,'stdout','-l','eng','--psm','11','tsv'],{timeout:20000,maxBuffer:256*1024});
 const rows=stdout.trim().split('\n').slice(1).map(line=>line.split('\t'));
 const row=rows.find(c=>c.length>=12&&c[11].toLowerCase()===word.toLowerCase()&&(!topOnly||Number(c[7])/ratio<90));
 assert.ok(row,`Actual rendered control ${word} must be readable before activation`);
 return{x:(Number(row[6])+Number(row[8])/2)/ratio,y:(Number(row[7])+Number(row[9])/2)/ratio};
}
export function requireChatText(text,{fixtures=false}={}){
 assert.match(text,/\bconversations?\b/i,'Actual canvas screenshot must contain readable conversation navigation');
 assert.match(text,fixtures?/\bfixture\b/i:/\bdraft\b/i,'Actual canvas screenshot must contain its truthful draft/fixture state');
}
