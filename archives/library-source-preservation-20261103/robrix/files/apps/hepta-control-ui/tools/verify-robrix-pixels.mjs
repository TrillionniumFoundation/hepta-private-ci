// QA tooling only. Reads actual host screenshots; never supplies UI text.
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import assert from 'node:assert/strict';
const run=promisify(execFile);
export async function readScreenshotText(path){
 const {stdout}=await run('tesseract',[path,'stdout','-l','eng','--psm','11'],{timeout:20000,maxBuffer:65536});
 return stdout;
}
export function requireChatText(text,{fixtures=false}={}){
 assert.match(text,/\bconversations?\b/i,'Actual canvas screenshot must contain readable conversation navigation');
 assert.match(text,fixtures?/\bfixture\b/i:/\bdraft\b/i,'Actual canvas screenshot must contain its truthful draft/fixture state');
}
