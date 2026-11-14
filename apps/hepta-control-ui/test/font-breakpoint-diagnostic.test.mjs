import {test} from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {createHash} from 'node:crypto';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {observeFontDelivery,sdkProbeLocations,validateDelivery} from '../tools/font-delivery-diagnostic.mjs';

// In-memory CDP-shaped doubles only: no browser, inspector, sockets or application execution.
const source=`class Host {
 constructor() { this.wasm_app = this.wasm_create_app(); }
 async consume(entry,reader) {
  const item = await reader.read();
  if(item.done){break;}
  response_body.set(chunk,body_at);
  let body_u8 = this.array_to_u8(response_body);
  entry.response_bytes = response_body.length;
  this.exports.wasm_network_http_response();
 }
 network_http_finish(entry) {
  if(entry.stall_timer) {}
 }
}`;
const scriptId='sdk-1',instrumentation='instrumentation';
const eventAt=(location,ids=[])=>({callFrames:[{callFrameId:'frame',location}],hitBreakpoints:ids});
const withScript=location=>({scriptId,...location});
const plain=({scriptId,lineNumber,columnNumber})=>({scriptId,lineNumber,columnNumber});

async function harness(t,options={}){
 const script=options.source??source,consumer=options.consumer!==false;
 const probes=sdkProbeLocations(script,{consumer});
 const call=consumer?{...withScript(probes.consumer.callStart),columnNumber:probes.consumer.callStart.columnNumber+5,type:'call'}:null;
 const session=new EventEmitter(),page=new EventEmitter(),calls=[],resumeWaiters=[],enableNonces=[];
 let sets=0,detached=false,removeInstrumentationCalls=0;
 const receiver={exports:{
  hepta_font_consumer_enable(nonce){enableNonces.push(nonce);return options.nonceResult??1;},
  hepta_font_consumer_seal(){return 1;},hepta_font_consumer_snapshot_ptr(){return 4;},hepta_font_consumer_snapshot_len(){return 1;},
 },memory:{buffer:new ArrayBuffer(16)}};
 if(options.missingExport)delete receiver.exports[options.missingExport];
 session.send=async(method,args={})=>{
  calls.push({method,args:structuredClone(args)});
  if(method===options.failMethod)throw new Error('mock '+method+' failed');
  if(method==='Debugger.setInstrumentationBreakpoint')return {breakpointId:instrumentation};
  if(method==='Debugger.getScriptSource')return {scriptSource:options.servedSource??script};
  if(method==='Debugger.getPossibleBreakpoints')return {locations:options.possible?options.possible({call,probes,args}):[withScript(probes.consumer.start),call]};
  if(method==='Debugger.setBreakpoint'){
   const index=++sets;
   if(index===options.failSet)throw new Error('mock set '+index+' failed');
   return {breakpointId:options.breakpointId?options.breakpointId(index):'point-'+index,actualLocation:options.actual?options.actual(args.location,index):args.location};
  }
  if(method==='Debugger.removeBreakpoint'){
   if(args.breakpointId===instrumentation&&++removeInstrumentationCalls===1&&options.failInstrumentationRemoval)throw new Error('mock instrumentation removal failed');
   if(options.cleanupFail?.includes(args.breakpointId))throw new Error('mock cleanup '+args.breakpointId+' failed');
  }
  if(method==='Debugger.evaluateOnCallFrame'){
   if(args.expression.includes('hepta_font_consumer_enable')){
    if(options.evaluateFailure)return {exceptionDetails:{text:'mock evaluation failure'}};
    try{
     // Execute only the diagnostic enable expression against inert JS exports.
     new Function('return '+args.expression).call(receiver);
     return {result:options.missingObject?{}:{objectId:'consumer-object'}};
    }catch(error){return {exceptionDetails:{text:String(error)}};}
   }
   return {result:{}};
  }
  if(method==='Runtime.callFunctionOn')return {exceptionDetails:{text:'snapshot intentionally unavailable in setup mock'}};
  if(method==='Debugger.resume')resumeWaiters.shift()?.();
  return {};
 };
 session.detach=async()=>{detached=true;};
 page.context=()=>({newCDPSession:async()=>session});
 page.addInitScript=async()=>{};
 page.evaluate=async()=>{
  if(options.collectFailure)throw new Error('mock collection failed');
  return {records:[],finishes:[],overflow:0};
 };
 const manifest={fixtures:!consumer,threads:false,files:{'makepad_platform/web.js':{sha256:createHash('sha256').update(script).digest('hex')}}};
 const observer=await observeFontDelivery(page,manifest),directory=await mkdtemp(join(tmpdir(),'font-breakpoint-mock-'));
 t.after(()=>rm(directory,{recursive:true,force:true}));
 const pause=event=>new Promise(resolve=>{resumeWaiters.push(resolve);session.emit('Debugger.paused',event);});
 session.emit('Debugger.scriptParsed',{scriptId,url:'https://example.invalid/makepad_platform/web.js'});
 return {calls,probes,call,enableNonces,manifest,pause,
  setup:()=>pause(eventAt({scriptId,lineNumber:0,columnNumber:0})),
  async report(){await observer.close(join(directory,'report.json'),{priorFailure:true});assert.equal(detached,true);return JSON.parse(await readFile(join(directory,'report.json'),'utf8'));},
 };
}
const sent=(h,method)=>h.calls.filter(call=>call.method===method);
const removed=h=>sent(h,'Debugger.removeBreakpoint').map(call=>call.args.breakpointId);

test('consumer source range encloses only the unique complete call statement',()=>{
 for(const script of [source,source.replaceAll(' = ','='),source.replaceAll('\n',' '),source.replace(' = ','\n =\n ')]){
  const {consumer}=sdkProbeLocations(script,{consumer:true});
  const lines=script.split('\n'),offset=position=>lines.slice(0,position.lineNumber).reduce((n,line)=>n+line.length+1,0)+position.columnNumber;
  assert.equal(script.slice(offset(consumer.callStart),offset(consumer.end)),'this.wasm_create_app()');
  assert.match(script.slice(offset(consumer.start),offset(consumer.end)),/^this\.wasm_app\s*=\s*this\.wasm_create_app\(\)$/);
 }
});
for(const [name,change]of Object.entries({
 missing:s=>s.replace('this.wasm_app = this.wasm_create_app();',''),
 duplicate:s=>s+'this.wasm_app = this.wasm_create_app();',
 renamed:s=>s.replace('this.wasm_create_app()','this.other()'),
 arguments:s=>s.replace('this.wasm_create_app()','this.wasm_create_app(1)'),
 chained:s=>s.replace('this.wasm_create_app();','this.wasm_create_app().other();'),
 unterminated:s=>s.replace('this.wasm_create_app();','this.wasm_create_app()'),
 prefixed:s=>s.replace('this.wasm_app','otherthis.wasm_app'),
}))test('consumer source rejects '+name,()=>assert.throws(()=>sdkProbeLocations(change(source),{consumer:true})));

test('setup selects the sole RHS call and retains requested selected actual and pause evidence',async t=>{
 const h=await harness(t);await h.setup();await h.pause(eventAt(plain(h.call),['point-1']));
 const report=await h.report(),expected=plain(h.call);
 assert.deepEqual(sent(h,'Debugger.getPossibleBreakpoints').map(item=>item.args),[{start:withScript(h.probes.consumer.start),end:withScript(h.probes.consumer.end),restrictToFunction:true}]);
 assert.deepEqual(report.breakpointEvidence[0],{kind:'consumer',requested:{start:withScript(h.probes.consumer.start),end:withScript(h.probes.consumer.end)},selected:expected,actual:expected,pause:expected});
 assert.deepEqual([report.installed,report.setupState,report.errors,report.breakpointEvidence.length,h.enableNonces.length],[true,'installed',[],3,1]);
 assert.ok(Number.isInteger(h.enableNonces[0])&&h.enableNonces[0]>0);
 assert.deepEqual(removed(h),[instrumentation]);
});

for(const [name,possible]of Object.entries({
 empty:()=>[],
 nonarray:()=>null,
 oversized:({call})=>Array(17).fill(call),
 commonOnly:({call})=>[{...call,type:undefined}],
 returnOnly:({call})=>[{...call,type:'return'}],
 twoCalls:({call})=>[call,{...call,columnNumber:call.columnNumber+1}],
 wrongScript:({call})=>[{...call,scriptId:'other'}],
 missingColumn:({call})=>[{...call,columnNumber:undefined}],
 negativeLine:({call})=>[{...call,lineNumber:-1}],
 fractionalColumn:({call})=>[{...call,columnNumber:0.5}],
 longScript:({call})=>[{...call,scriptId:'x'.repeat(129)}],
 beforeStart:({probes})=>[{...withScript(probes.consumer.start),columnNumber:probes.consumer.start.columnNumber-1,type:'call'}],
 atEnd:({probes})=>[{...withScript(probes.consumer.end),type:'call'}],
 afterEnd:({probes})=>[{...withScript(probes.consumer.end),columnNumber:probes.consumer.end.columnNumber+1,type:'call'}],
 beforeRhs:({probes})=>[{...withScript(probes.consumer.start),type:'call'}],
 outOfRangeExtra:({call})=>[call,{scriptId,lineNumber:1000,columnNumber:0}],
}))test('setup rejects '+name+' candidate results without retry',async t=>{
 const h=await harness(t,{possible});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState,report.errors.length,sent(h,'Debugger.getScriptSource').length,sent(h,'Debugger.setBreakpoint').length],[false,'failed',1,1,0]);
 assert.deepEqual(removed(h),[instrumentation]);assert.equal(validateDelivery(report,h.manifest),false);
});

for(const [name,actual]of Object.entries({
 column:location=>({...location,columnNumber:location.columnNumber+1}),
 line:location=>({...location,lineNumber:location.lineNumber+1}),
 script:location=>({...location,scriptId:'other'}),
 missing:()=>undefined,
 malformed:()=>({scriptId:'x'.repeat(10000),lineNumber:NaN,columnNumber:Infinity}),
}))test('actual '+name+' mismatch rolls back the returned ID and retains bounded evidence',async t=>{
 const h=await harness(t,{actual});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState,sent(h,'Debugger.setBreakpoint').length],[false,'failed',1]);
 assert.match(report.errors[0],/SDK diagnostic breakpoint moved/);assert.deepEqual(removed(h),['point-1',instrumentation]);
 assert.ok(JSON.stringify(report.breakpointEvidence).length<1000);
});

for(const failSet of [1,2,3])test('set failure '+failSet+' removes all earlier IDs and never retries',async t=>{
 const h=await harness(t,{failSet});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual(removed(h),[...Array.from({length:failSet-1},(_,i)=>'point-'+(i+1)),instrumentation]);
 assert.deepEqual([report.installed,report.setupState,sent(h,'Debugger.setBreakpoint').length],[false,'failed',failSet]);
 assert.match(report.errors[0],new RegExp('mock set '+failSet+' failed'));
});
for(const [name,id]of Object.entries({absent:undefined,null:null,number:2,boolean:false,object:{},array:[],empty:'',oversized:'x'.repeat(257)})){
 test('malformed '+name+' breakpoint ID cannot publish a partial install',async t=>{
  const h=await harness(t,{breakpointId:index=>index===2?id:'point-'+index});await h.setup();await h.setup();const report=await h.report();
  assert.deepEqual([report.installed,report.setupState,sent(h,'Debugger.setBreakpoint').length],[false,'failed',2]);
  assert.deepEqual(removed(h),['point-1',instrumentation]);assert.match(report.errors[0],/breakpoint ID invalid or reused/);
 });
}
test('duplicate returned breakpoint IDs fail and remove each valid ID once',async t=>{
 const h=await harness(t,{breakpointId:()=> 'point-1'});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState,sent(h,'Debugger.setBreakpoint').length],[false,'failed',2]);
 assert.deepEqual(removed(h),['point-1',instrumentation]);assert.match(report.errors[0],/breakpoint ID invalid or reused/);
});
test('returned instrumentation ID cannot be reused as a consumer breakpoint',async t=>{
 const h=await harness(t,{breakpointId:()=>instrumentation});await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState],[false,'failed']);assert.deepEqual(removed(h),[instrumentation]);
 assert.match(report.errors[0],/breakpoint ID invalid or reused/);
});
for(const movedIndex of [2,3])test('later moved breakpoint '+movedIndex+' rolls back its own returned ID too',async t=>{
 const h=await harness(t,{actual:(location,index)=>index===movedIndex?{...location,lineNumber:location.lineNumber+1}:location});
 await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual(removed(h),[...Array.from({length:movedIndex},(_,i)=>'point-'+(i+1)),instrumentation]);
 assert.deepEqual([report.installed,report.setupState,sent(h,'Debugger.setBreakpoint').length],[false,'failed',movedIndex]);
 assert.match(report.errors[0],/SDK diagnostic breakpoint moved/);
});
for(const failMethod of ['Debugger.getScriptSource','Debugger.getPossibleBreakpoints'])test(failMethod+' rejection is terminal',async t=>{
 const h=await harness(t,{failMethod});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState,sent(h,failMethod).length],[false,'failed',1]);assert.deepEqual(removed(h),[instrumentation]);
});
test('source digest mismatch cannot install any breakpoint or retry',async t=>{
 const h=await harness(t,{servedSource:source+' '});await h.setup();await h.setup();const report=await h.report();
 assert.match(report.errors[0],/digest mismatch/);assert.equal(sent(h,'Debugger.setBreakpoint').length,0);assert.equal(sent(h,'Debugger.getScriptSource').length,1);
});
test('instrumentation removal failure rolls back the complete partial transaction',async t=>{
 const h=await harness(t,{failInstrumentationRemoval:true});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState],[false,'failed']);
 assert.deepEqual(removed(h),[instrumentation,'point-1','point-2','point-3',instrumentation]);
 assert.match(report.errors[0],/instrumentation removal failed/);
});
test('cleanup failures preserve the original error and attempt every remaining removal',async t=>{
 const h=await harness(t,{failSet:3,cleanupFail:['point-1',instrumentation]});await h.setup();await h.setup();const report=await h.report();
 assert.deepEqual(removed(h),['point-1','point-2',instrumentation]);
 assert.match(report.errors[0],/mock set 3 failed/);assert.equal(report.errors.length,3);assert.equal(report.installed,false);
});
test('back-to-back paused events cannot overlap or repeat setup',async t=>{
 const h=await harness(t);await Promise.all([h.setup(),h.setup()]);const report=await h.report();
 assert.deepEqual([report.installed,sent(h,'Debugger.getScriptSource').length,sent(h,'Debugger.setBreakpoint').length],[true,1,3]);
});

for(const field of ['scriptId','lineNumber','columnNumber'])test('consumer pause '+field+' mismatch cannot enable or retry enable',async t=>{
 const h=await harness(t);await h.setup();const bad={...plain(h.call),[field]:field==='scriptId'?'other':h.call[field]+1};
 await h.pause(eventAt(bad,['point-1']));await h.pause(eventAt(plain(h.call),['point-1']));const report=await h.report();
 assert.deepEqual(h.enableNonces,[]);assert.equal(sent(h,'Debugger.evaluateOnCallFrame').length,0);
 assert.match(report.errors[0],/pause location mismatch/);assert.match(report.errors[1],/Unexpected consumer enable boundary/);
 assert.deepEqual(report.breakpointEvidence[0].pause,bad);
});
for(const [name,options]of Object.entries({
 missingExport:{missingExport:'hepta_font_consumer_seal'},
 rejectedNonce:{nonceResult:0},
 exception:{evaluateFailure:true},
 missingObject:{missingObject:true},
}))test('consumer '+name+' remains failed and cannot evaluate enable twice',async t=>{
 const h=await harness(t,options);await h.setup();await h.pause(eventAt(plain(h.call),['point-1']));await h.pause(eventAt(plain(h.call),['point-1']));
 const report=await h.report();assert.match(report.errors[0],/Consumer enable failed/);assert.match(report.errors[1],/Unexpected consumer enable boundary/);
 assert.equal(sent(h,'Debugger.evaluateOnCallFrame').length,1);assert.equal(report.passed,false);
});
test('a repeated successful consumer boundary is still rejected',async t=>{
 const h=await harness(t);await h.setup();await h.pause(eventAt(plain(h.call),['point-1']));await h.pause(eventAt(plain(h.call),['point-1']));
 const report=await h.report();assert.equal(h.enableNonces.length,1);assert.match(report.errors[0],/Unexpected consumer enable boundary/);
});
for(const [kind,id]of [['delivery','point-2'],['finish','point-3']])test(kind+' before consumer enable cannot record evidence',async t=>{
 const h=await harness(t);await h.setup();await h.pause(eventAt(withScript(h.probes[kind]),[id]));const report=await h.report();
 assert.match(report.errors[0],/delivery before consumer enable/);assert.equal(sent(h,'Debugger.evaluateOnCallFrame').length,0);
 assert.deepEqual([report.records,report.finishes,report.passed],[[],[],false]);
});
test('consumer success permits later delivery evaluation',async t=>{
 const h=await harness(t);await h.setup();await h.pause(eventAt(plain(h.call),['point-1']));await h.pause(eventAt(withScript(h.probes.delivery),['point-2']));
 const report=await h.report();assert.deepEqual(report.errors,[]);assert.equal(sent(h,'Debugger.evaluateOnCallFrame').length,2);
});
test('consumer-disabled fixtures retain same-line delivery selection without consumer discovery',async t=>{
 const h=await harness(t,{consumer:false,actual:location=>({...location,columnNumber:location.columnNumber+1})});
 await h.setup();await h.pause(eventAt(withScript(h.probes.delivery),['point-1']));const report=await h.report();
 assert.deepEqual([report.installed,report.errors,report.breakpointEvidence.length],[true,[],2]);
 assert.equal(sent(h,'Debugger.getPossibleBreakpoints').length,0);assert.equal(h.enableNonces.length,0);assert.equal(sent(h,'Debugger.evaluateOnCallFrame').length,1);
 assert.equal('consumerValidation'in report,false);
});
test('consumer-disabled fixture source does not need an app-creation statement',async t=>{
 const h=await harness(t,{consumer:false,source:source.replace('this.wasm_app = this.wasm_create_app();','')});
 await h.setup();const report=await h.report();assert.deepEqual([report.installed,report.errors,report.breakpointEvidence.length],[true,[],2]);
 assert.equal(sent(h,'Debugger.getPossibleBreakpoints').length,0);
});
test('collection failures still preserve bounded setup evidence',async t=>{
 const h=await harness(t,{collectFailure:true});await h.setup();const report=await h.report();
 assert.deepEqual([report.installed,report.setupState,report.breakpointEvidence.length],[true,'installed',3]);assert.match(report.errors[0],/collection failed/);
});
