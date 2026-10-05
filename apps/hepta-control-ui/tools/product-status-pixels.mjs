// Fixed OCR observations of one immutable rendered image; no text substitution.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {readScreenshotText} from './verify-robrix-pixels.mjs';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export function productStatusTextMatches(text,state){
 const common=[/not current write authority/i,/commands remain unavailable/i];
 const specific={
  notAttached:[/Production owner:\s*not attached/i,/No lease observation is available/i,/runtime unavailable\s*\(Transport\)/i],
  timedOut:[/Production owner observation unavailable\s*\(TimedOut\)/i],
  noObservation:[/No owner observation has been requested/i],
 };
 assert.ok(Object.hasOwn(specific,state),'Unknown product status observation');
 return [...common,...specific[state]].every(pattern=>pattern.test(text));
}
export async function readProductStatusPixels(path,state){
 const png=await readFile(path),original=await readScreenshotText(path,{language:'eng'});
 const block=productStatusTextMatches(original,state)?null:await readScreenshotText(path,{language:'eng',layout:'block'});
 const text=block===null?original:original+'\n'+block;
 assert.equal(sha(await readFile(path)),sha(png),'Status PNG changed during OCR');
 return {state,sourcePngSha256:sha(png),original,block,text,passed:productStatusTextMatches(text,state)};
}
