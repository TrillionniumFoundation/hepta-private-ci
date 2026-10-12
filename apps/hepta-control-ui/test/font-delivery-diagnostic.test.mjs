import {test} from 'node:test';
import './font-diagnostic-browser-identity.test.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {sdkProbeLocations,validateDelivery} from '../tools/font-delivery-diagnostic.mjs';
import {EventEmitter} from 'node:events';
import {writeControl,CONTROL_BODY} from '../tools/font-transport-fixture.mjs';
const source=`async function consume(){
 const item = await reader.read();
 if(item.done){break;}
 response_body.set(chunk,body_at);
 let body_u8=this.array_to_u8(response_body);
 entry.response_bytes=response_body.length;
 this.exports.wasm_network_http_response();
}
class Host {
 network_http_finish(entry) {
  if(entry.stall_timer) {}
 }
}`;
test('source locations are exact and reject changed or duplicated boundaries',()=>{
 assert.deepEqual(sdkProbeLocations(source),{delivery:{lineNumber:6,columnNumber:1},finish:{lineNumber:10,columnNumber:2}});
 for(const changed of [source.replace('await reader.read()','await response.arrayBuffer()'),source+source,source.replace('network_http_finish','other')])assert.throws(()=>sdkProbeLocations(changed));
});
const manifest={files:{'font.otf':{bytes:4,sha256:'a'.repeat(64)}}};
const good=()=>({installed:true,errors:[],overflow:0,requests:['/font.otf'],records:[{path:'/font.otf',key:'1',bytes:4,wasmBytes:4,sha256:'a'.repeat(64),eof:true}],finishes:[{key:'1',bytes:4,aborted:false}]});
test('requires EOF, exact manifest bytes/hash and nonaborted normal finalization',()=>{
 assert.equal(validateDelivery(good(),manifest),true);
 for(const change of [
  r=>r.records[0].bytes--,r=>r.records[0].wasmBytes--,r=>r.records[0].eof=false,
  r=>r.records[0].sha256='b'.repeat(64),r=>r.finishes[0].aborted=true,
  r=>r.finishes=[],r=>r.records.push(r.records[0]),r=>r.requests=[],
  r=>r.installed=false,r=>r.errors.push('probe failed'),r=>r.overflow++,
 ]){const result=good();change(result);assert.equal(validateDelivery(result,manifest),false);}
});
test('opt-in config cannot replace primary config or omit strict product cases',async()=>{
 const config=await readFile(new URL('../playwright.font-diagnostic.config.mjs',import.meta.url),'utf8');
 assert.match(config,/hashDiagnosticFile\(executablePath\)!==FIXED_BINARY_SHA/);
 assert.match(config,/\['baseline','fixed'\]/);assert.match(config,/\[false,true\]/);
 assert.match(config,/robrix-product-status\.spec\.mjs/);
 const primary=await readFile(new URL('../playwright.product.config.mjs',import.meta.url),'utf8');
 assert.doesNotMatch(primary,/DIAGNOSTIC|executablePath|continue-on-error/);
 const spec=await readFile(new URL('../e2e/robrix-product-status.spec.mjs',import.meta.url),'utf8');
 assert.match(spec,/expect\(faults\)\.toEqual\(\[\]\)/);
 assert.match(spec,/expect\(requests\)\.toEqual\(\[\]\)/);
 assert.match(spec,/for\(const width of \[1280,640\]\)for\(const scenario of \['timeout','navigation','background'\]\)/);
 const observer=await readFile(new URL('../tools/font-delivery-diagnostic.mjs',import.meta.url),'utf8');
 assert.doesNotMatch(observer,/\.clone\(|\.tee\(|\.getReader\(|\.arrayBuffer\(|route\.fulfill|Fetch\.enable|setCacheDisabled/);
 assert.match(observer,/Debugger\.getScriptSource/);assert.match(observer,/SDK diagnostic breakpoint moved/);
});
test('truncation closes the real socket short of declared length; complete reaches end',async()=>{
 for(const kind of ['complete','truncated','abort','declared-limit','stream-limit']){
  const response=new EventEmitter(),record={},writes=[];let ended=false,fin=false,headers;
  Object.assign(response,{destroyed:false,socket:{end(){fin=true;}},
   writeHead(status,value){assert.equal(status,200);headers=value;},
   write(value){writes.push(Buffer.from(value));},
   end(value){if(value)writes.push(Buffer.from(value));ended=true;response.emit('finish');},
  });
  writeControl(response,kind,record);
  await new Promise(resolve=>setTimeout(resolve,40));
  assert.equal(headers['Cache-Control'],'no-store');
  if(kind==='truncated'){
   assert.equal(headers['Content-Length'],'12');assert.equal(Buffer.concat(writes).length,11);
   assert.equal(fin,true);assert.equal(ended,false);
  }else if(kind==='abort'){assert.equal(ended,false);assert.equal(fin,false);}
  else{
   assert.equal(ended,true);assert.equal(record.finished,true);
   assert.equal(Buffer.concat(writes).length,kind==='declared-limit'?256:kind==='stream-limit'?267:CONTROL_BODY.length);
  }
  response.emit('close');
 }
});

test('every manifest font is mandatory, with no duplicates or outside paths',()=>{
 const catalog={files:Object.fromEntries(Array.from({length:8},(_,i)=>['font'+i+'.otf',{bytes:4,sha256:'a'.repeat(64)}]))};
 const complete={installed:true,errors:[],overflow:0,
  requests:Object.keys(catalog.files).map(path=>'/'+path),
  records:Object.keys(catalog.files).map((path,i)=>({...good().records[0],path:'/'+path,key:String(i)})),
  finishes:Object.keys(catalog.files).map((_,i)=>({...good().finishes[0],key:String(i)})),
 };
 assert.equal(validateDelivery(complete,catalog),true);
 for(const change of [
  r=>{r.requests.splice(1);r.records.splice(1);r.finishes.splice(1);},
  r=>r.requests[7]=r.requests[0],r=>r.requests[7]='/outside.otf',
  r=>r.records[7].path=r.records[0].path,r=>r.finishes.push(r.finishes[0]),
 ]){const observed=structuredClone(complete);change(observed);assert.equal(validateDelivery(observed,catalog),false);}
});

test('diagnostic pixel plans require all projects, captures and source identity',async()=>{
 const {requireDiagnosticPlan,verifyDiagnosticEvidence,DIAGNOSTIC_PROJECTS}=await import('../tools/verify-font-diagnostic-evidence.mjs');
 const {captureSchedule}=await import('../tools/robrix-pixel-plan.mjs');
 const {mkdtemp,rm}=await import('node:fs/promises');const {tmpdir}=await import('node:os');const {join}=await import('node:path');
 const subject={project:'fixed-untouched',initialWidth:1280,sourceSha:'a'.repeat(40)};
 const plan={...subject,diagnosticOnly:true,browser:'chromium',fixtures:true,captures:captureSchedule(1280,true)};
 assert.deepEqual(requireDiagnosticPlan(plan,subject),captureSchedule(1280,true));
 for(const change of [p=>p.captures.pop(),p=>p.captures[1]=p.captures[0],p=>p.project='chromium',p=>p.sourceSha='b'.repeat(40),p=>p.diagnosticOnly=false,p=>p.fixtures=false]){
  const invalid=structuredClone(plan);change(invalid);assert.throws(()=>requireDiagnosticPlan(invalid,subject));
 }
 assert.deepEqual(DIAGNOSTIC_PROJECTS,['baseline-untouched','baseline-sdk-observed','fixed-untouched','fixed-sdk-observed']);
 const root=await mkdtemp(join(tmpdir(),'font-pixel-missing-'));
 try{const result=await verifyDiagnosticEvidence(root,subject.sourceSha);assert.equal(result.passed,false);assert.equal(result.results.length,8);assert.equal(result.captures.required,104);assert.equal(result.captures.passed,0);assert.equal(result.semanticChecks.evaluated,0);}
 finally{await rm(root,{recursive:true,force:true});}
});

test('optional bounded diagnostics follow primary evidence and retain pixel failure reports',async()=>{
 const workflow=await readFile(new URL('../../../.github/workflows/ui-product-foundation.yml',import.meta.url),'utf8');
 assert.ok(workflow.indexOf('- id: font_diagnostic_browser')>workflow.indexOf('path: apps/hepta-control-ui/test-results/evidence-groups/summary/'));
 const diagnostic=workflow.slice(workflow.indexOf('- id: font_diagnostic_browser'));
 assert.equal((diagnostic.match(/timeout-minutes:/g)??[]).length,5);
 assert.match(workflow,/timeout-minutes: 60/);
 assert.ok(diagnostic.indexOf('verify-font-diagnostic-evidence.mjs')<diagnostic.indexOf('Preserve failed and successful font diagnostic arms'));
 assert.match(diagnostic,/font-diagnostic-\*-results\.json/);
 const transport=await readFile(new URL('../e2e/robrix-font-transport.spec.mjs',import.meta.url),'utf8');
 assert.match(transport,/test\.skip\([^;]*fontDeliveryObserver/);
 const verifier=await readFile(new URL('../tools/verify-font-diagnostic-evidence.mjs',import.meta.url),'utf8');
 assert.match(verifier,/await verifyCapture\(directory,entry,item\)/);
 assert.match(verifier,/process\.exitCode=1/);
 assert.match(verifier,/emoji is Rust family-state evidence only/);
});
