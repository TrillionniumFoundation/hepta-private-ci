import './font-consumer-diagnostic.test.mjs';
import './font-breakpoint-diagnostic.test.mjs';
import {test} from 'node:test';
import './font-diagnostic-browser-identity.test.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {REQUIRED_PRODUCT_FONT_PATHS,sdkProbeLocations,validateDelivery} from '../tools/font-delivery-diagnostic.mjs';
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
const manifest={files:Object.fromEntries(REQUIRED_PRODUCT_FONT_PATHS.map(path=>[path.slice(1),{bytes:4,sha256:'a'.repeat(64)}]))};
const good=()=>({installed:true,errors:[],overflow:0,requests:[...REQUIRED_PRODUCT_FONT_PATHS],
 records:REQUIRED_PRODUCT_FONT_PATHS.map((path,i)=>({path,key:String(i),bytes:4,wasmBytes:4,sha256:'a'.repeat(64),eof:true})),
 finishes:REQUIRED_PRODUCT_FONT_PATHS.map((_,i)=>({key:String(i),bytes:4,aborted:false})),
});
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
 // The product pin is independent of opt-in diagnostics and cannot accept an
 // arbitrary executable: both the configured file and the running image are checked.
 assert.doesNotMatch(primary,/DIAGNOSTIC|diagnosticOnly|fontDeliveryObserver|continue-on-error/);
 assert.deepEqual([...primary.matchAll(/process\.env\.([A-Z_]+)/g)].map(match=>match[1]),['HEPTA_PRODUCT_BROWSER']);
 assert.match(primary,/import \{hashDiagnosticFile,FIXED_BINARY_SHA,FIXED_BROWSER_VERSION\} from '\.\/tools\/font-diagnostic-browser-identity\.mjs';/);
 assert.match(primary,/^const executablePath=process\.env\.HEPTA_PRODUCT_BROWSER;$/m);
 assert.match(primary,/^if\(executablePath&&await hashDiagnosticFile\(executablePath\)!==FIXED_BINARY_SHA\)throw new Error\('Product browser digest mismatch'\);$/m);
 assert.match(primary,/launchOptions:\{executablePath:resolve\(executablePath\)\}/);
 assert.equal((primary.match(/launchOptions:/g)??[]).length,1);
 assert.match(primary,/metadata:\{productBrowserQualification:true,expectedBrowser:FIXED_BROWSER_VERSION\}/);
 assert.match(primary,/testMatch:\['robrix-product-status\.spec\.mjs','robrix-font-transport\.spec\.mjs'\]/);
 const identity=await readFile(new URL('../tools/font-diagnostic-browser-identity.mjs',import.meta.url),'utf8');
 assert.match(identity,/export const FIXED_BINARY_SHA='37164bfc553db9c17e11bc19c291738a1179c5b13529ec6f20a39bd665e91be0';/);
 assert.match(identity,/export const FIXED_BROWSER_VERSION='157\.0\.8099\.0';/);
 for(const guard of [
  "testInfo.project.metadata.productBrowserQualification!==true||testInfo.project.metadata.expectedBrowser!==FIXED_BROWSER_VERSION",
  "const executable=await io.open(`/proc/${pid}/exe`,'r');",
  "const path=await io.readlink(`/proc/${pid}/exe`);",
  'record.executablePath=path;',
  'executable.createReadStream({autoClose:false})',
  'if(browser.version()!==testInfo.project.metadata.expectedBrowser)throw',
  'if(record.executableSha256!==FIXED_BINARY_SHA)throw',
  "if(!['@94bcda4759263b9a241f5008a68e753c2ebe3081','@3cdad9004f922728bfc61639d120b2ef4bddaf72'].includes(version.revision))throw",
  "if(scope==='product'&&!['Chrome/'+FIXED_BROWSER_VERSION,'HeadlessChrome/'+FIXED_BROWSER_VERSION].includes(version.product))throw",
 ])assert.ok(identity.includes(guard),`Missing product browser identity guard: ${guard}`);
 const spec=await readFile(new URL('../e2e/robrix-product-status.spec.mjs',import.meta.url),'utf8');
 assert.match(spec,/expect\(faults\)\.toEqual\(\[\]\)/);
 assert.match(spec,/expect\(requests\)\.toEqual\(\[\]\)/);
 assert.match(spec,/for\(const width of \[1280,640\]\)for\(const scenario of \['timeout','navigation','background'\]\)/);
 const transport=await readFile(new URL('../e2e/robrix-font-transport.spec.mjs',import.meta.url),'utf8');
 for(const source of [spec,transport]){
  assert.match(source,/import \{recordProductBrowser\} from '\.\.\/tools\/font-diagnostic-browser-identity\.mjs';/);
  assert.match(source,/const browserIdentity=await recordProductBrowser\(browser,testInfo\);/);
 }
 assert.match(transport,/const productQualification=testInfo\.project\.metadata\.productBrowserQualification===true;/);
 assert.match(transport,/test\.skip\(\(!testInfo\.project\.metadata\.diagnosticOnly&&!productQualification\)\|\|testInfo\.project\.metadata\.fontDeliveryObserver,/);
 assert.match(transport,/\.\.\.\['complete','revalidated','truncated','abort','declared-limit','stream-limit'\]\.map\(kind=>\(\{kind,cache:null\}\)\)/);
 assert.match(transport,/\.\.\.\['truncated','abort','declared-limit','stream-limit'\]\.map\(kind=>\(\{kind,cache:'private'\}\)\)/);
 assert.match(transport,/for\(const \{kind,cache\} of controls\)/);
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

test('product coverage is mandatory while unrequested packaged fonts are optional',()=>{
 const unused=['IBMPlexSans-BoldItalic.ttf','IBMPlexSans-Italic.ttf','LiberationMono-Regular.ttf','fa-solid-900.ttf'];
 const catalog={files:{...manifest.files,...Object.fromEntries(unused.map(name=>['makepad_widgets/resources/'+name,{bytes:4,sha256:'a'.repeat(64)}]))}};
 const complete=good();
 assert.equal(Object.keys(catalog.files).length,12);
 assert.equal(validateDelivery(complete,catalog),true);
 for(const change of [
  r=>{r.requests.splice(1);r.records.splice(1);r.finishes.splice(1);},
  r=>r.requests[7]=r.requests[0],r=>r.requests[7]='/outside.otf',
  r=>r.records[7].path=r.records[0].path,r=>r.finishes.push(r.finishes[0]),
 ]){const observed=structuredClone(complete);change(observed);assert.equal(validateDelivery(observed,catalog),false);}
});

test('required coverage follows Rust font families and explicit math asset registration',async()=>{
 const styles=await readFile(new URL('../rust/robrix-ui/src/robrix/styles.rs',import.meta.url),'utf8');
 const app=await readFile(new URL('../rust/robrix-ui/src/app.rs',import.meta.url),'utf8');
 const families=[...new Set([...styles.matchAll(/crate_resource\("([^":]+):([^"\n]+\.(?:ttf|otf))"\)/g)].map(match=>'/'+match[1]+'/'+match[2]))];
 assert.equal(families.length,7);
 assert.match(app,/app_main!\(App, font_set: International, font_assets: \[MATH_VIEW_FONT_ASSET\]/);
 assert.deepEqual([...REQUIRED_PRODUCT_FONT_PATHS].sort(),[...families,'/makepad_widgets/resources/NewCMMath-Regular.otf'].sort());
});

test('zero requests and each required-font omission fail even with matching remaining records',()=>{
 assert.equal(validateDelivery({...good(),requests:[],records:[],finishes:[]},manifest),false);
 for(const path of REQUIRED_PRODUCT_FONT_PATHS){
  const report=good(),key=report.records.find(record=>record.path===path).key;
  report.requests=report.requests.filter(request=>request!==path);
  report.records=report.records.filter(record=>record.path!==path);
  report.finishes=report.finishes.filter(finish=>finish.key!==key);
  assert.equal(validateDelivery(report,manifest),false,path);
  const reduced=structuredClone(manifest);delete reduced.files[path.slice(1)];
  assert.equal(validateDelivery(report,reduced),false,path);
  assert.equal(validateDelivery(good(),reduced),false,path);
 }
});

test('every additional requested font retains one-to-one manifest integrity and finalization',()=>{
 const path='/makepad_widgets/resources/IBMPlexSans-Italic.ttf';
 const catalog={files:{...manifest.files,[path.slice(1)]:{bytes:4,sha256:'a'.repeat(64)}}};
 const complete=good();complete.requests.push(path);
 complete.records.push({...complete.records[0],path,key:'optional'});
 complete.finishes.push({...complete.finishes[0],key:'optional'});
 assert.equal(validateDelivery(complete,catalog),true);
 for(const change of [
  r=>r.records.at(-1).bytes--,r=>r.records.at(-1).wasmBytes--,
  r=>r.records.at(-1).sha256='b'.repeat(64),r=>r.records.at(-1).eof=false,
  r=>r.finishes.at(-1).bytes--,r=>r.finishes.at(-1).aborted=true,
  r=>r.records.pop(),r=>r.finishes.pop(),r=>r.records.at(-1).path='/outside.otf',
  r=>r.finishes.at(-1).key='orphan',r=>r.records.at(-1).key=r.records[0].key,
  r=>r.requests.push(path),
 ]){const report=structuredClone(complete);change(report);assert.equal(validateDelivery(report,catalog),false);}
 assert.equal(validateDelivery(complete,manifest),false);
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
 // Later jobs own separate time budgets; only this job contains the diagnostic arms.
 const diagnostic=workflow.slice(workflow.indexOf('- id: font_diagnostic_browser')).split(/\n  [A-Za-z_][A-Za-z0-9_-]*:\s*\n/)[0];
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
