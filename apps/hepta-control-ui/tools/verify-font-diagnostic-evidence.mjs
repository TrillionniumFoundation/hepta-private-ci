// Separate diagnostic receipts; delegates every pixel assertion to the existing gate.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {verifyCapture} from './verify-robrix-evidence.mjs';
import {captureSchedule,expectedPixelChecks} from './robrix-pixel-plan.mjs';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export const DIAGNOSTIC_PROJECTS=['baseline-untouched','baseline-sdk-observed','fixed-untouched','fixed-sdk-observed'];
export function requireDiagnosticPlan(plan,{project,initialWidth,sourceSha}){
 assert.equal(plan.diagnosticOnly,true);
 assert.equal(plan.project,project);assert.equal(plan.sourceSha,sourceSha);
 assert.equal(plan.browser,'chromium');assert.equal(plan.initialWidth,initialWidth);assert.equal(plan.fixtures,true);
 const expected=captureSchedule(initialWidth,true);
 assert.ok(Array.isArray(plan.captures)&&plan.captures.length===expected.length,'Every diagnostic capture must exist');
 assert.equal(new Set(plan.captures.map(entry=>entry.name)).size,expected.length,'Duplicate diagnostic capture');
 assert.ok(plan.captures.every(entry=>expected.some(item=>item.name===entry.name)),'Unexpected diagnostic capture');
 return expected;
}
export async function verifyDiagnosticEvidence(root,sourceSha){
 assert.match(sourceSha,/^[0-9a-f]{40}$/);
 const results=[];
 for(const project of DIAGNOSTIC_PROJECTS)for(const initialWidth of [1280,640]){
  const subject={project,initialWidth};
  const directory=join(root,`robrix-host-Robrix-host-starts-under-strict-CSP-${initialWidth}-${project}`);
  try{
   const plan=JSON.parse(await readFile(join(directory,'pixel-plan.json'),'utf8'));
   const expected=requireDiagnosticPlan(plan,{...subject,sourceSha});
   for(const item of expected){
    try{
     const entry=plan.captures.find(value=>value.name===item.name);
     if(entry.observedThemePoint){
      const origin=plan.captures.find(value=>value.name===entry.observedThemePoint.sourceCapture);
      assert.ok(origin,'Observed control must name an actual capture from this subject');
      assert.deepEqual(origin.viewport,item.viewport);assert.equal(origin.theme,'Aurora');
      assert.equal(sha(await readFile(join(directory,origin.name+'.png'))),origin.pngSha256,'Theme locator source screenshot changed');
      assert.equal(origin.pngSha256,entry.observedThemePoint.sourcePngSha256);
     }
     const checks=await verifyCapture(directory,entry,item);
     assert.deepEqual(checks.map(check=>check.check),expectedPixelChecks(item));
     results.push({...subject,name:item.name,checks,passed:checks.every(check=>check.passed)});
    }catch(error){results.push({...subject,name:item.name,passed:false,error:String(error)});}
   }
  }catch(error){results.push({...subject,passed:false,error:String(error)});}
 }
 const required=[1280,640].flatMap(width=>captureSchedule(width,true));
 const assertions=results.flatMap(result=>result.checks??[]);
 const captures={required:required.length*DIAGNOSTIC_PROJECTS.length,passed:results.filter(result=>result.name&&result.passed).length};
 const semanticChecks={required:required.reduce((count,item)=>count+expectedPixelChecks(item).length,0)*DIAGNOSTIC_PROJECTS.length,evaluated:assertions.length,passed:assertions.filter(item=>item.passed).length};
 return {schema:'hepta.font-diagnostic-pixel-check.v1',diagnosticOnly:true,scope:'Existing CJK semantic pixel contract; emoji is Rust family-state evidence only',sourceSha,fixtures:true,captures,semanticChecks,results,passed:results.every(result=>result.passed)&&captures.passed===captures.required&&semanticChecks.passed===semanticChecks.required};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const [root]=process.argv.slice(2);assert.ok(root);
 const result=await verifyDiagnosticEvidence(root,process.env.SOURCE_SHA);
 await writeFile(join(root,'..','font-diagnostic-fixture-pixels-results.json'),JSON.stringify(result,null,2)+'\n');
 for(const failure of result.results.filter(item=>!item.passed))console.error(JSON.stringify(failure));
 console.log(`Diagnostic captures: ${result.captures.passed}/${result.captures.required}; semantic checks: ${result.semanticChecks.passed}/${result.semanticChecks.required}`);
 if(!result.passed)process.exitCode=1;
}
