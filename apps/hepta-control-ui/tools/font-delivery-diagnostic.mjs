// Opt-in debugger observation only. Does not replace Fetch, readers or SDK code.
import {createHash,randomInt} from 'node:crypto';
import {readConsumerSnapshot,validateConsumer,assertOptionalOutcome} from './font-consumer-diagnostic.mjs';
import {writeFile} from 'node:fs/promises';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const LIMIT=32,MAX_BYTES=128*1024*1024;
const sourceLocation=(source,offset)=>{
 const head=source.slice(0,offset);
 return {lineNumber:head.split('\n').length-1,columnNumber:offset-head.lastIndexOf('\n')-1};
};
const sameLocation=(a,b)=>a?.scriptId===b?.scriptId&&a?.lineNumber===b?.lineNumber&&a?.columnNumber===b?.columnNumber;
const positionBefore=(a,b)=>a.lineNumber<b.lineNumber||(a.lineNumber===b.lineNumber&&a.columnNumber<b.columnNumber);
const validLocation=value=>value&&typeof value.scriptId==='string'&&value.scriptId.length>0&&value.scriptId.length<=128
 &&Number.isSafeInteger(value.lineNumber)&&value.lineNumber>=0&&Number.isSafeInteger(value.columnNumber)&&value.columnNumber>=0;
const locationEvidence=value=>value?{
 scriptId:typeof value.scriptId==='string'?value.scriptId.slice(0,128):null,
 lineNumber:Number.isSafeInteger(value.lineNumber)?value.lineNumber:null,
 columnNumber:Number.isSafeInteger(value.columnNumber)?value.columnNumber:null,
}:null;
export function sdkProbeLocations(source,{consumer=false}={}){
 const ordered=[
  /const\s+item\s*=\s*await\s+reader\.read\(\)/g,
  /if\s*\(item\.done\)\s*\{\s*break;?\s*\}/g,
  /response_body\.set\(chunk,\s*body_at\)/g,
  /let\s+body_u8\s*=\s*this\.array_to_u8\(response_body\)/g,
  /entry\.response_bytes\s*=\s*response_body\.length/g,
  /this\.exports\.wasm_network_http_response\(/g,
 ].map(pattern=>{const matches=[...source.matchAll(pattern)];if(matches.length!==1)throw new Error('SDK EOF/delivery boundary changed');return matches[0].index;});
 if(ordered.some((offset,index)=>index&&offset<=ordered[index-1]))throw new Error('SDK EOF/delivery ordering changed');
 const locate=pattern=>{
  const matches=[...source.matchAll(pattern)];
  if(matches.length!==1)throw new Error('SDK diagnostic location is not unique');
  return sourceLocation(source,matches[0].index);
 };
 let consumerRange;
 if(consumer){
  const matches=[...source.matchAll(/(?<![\w$.])this\.wasm_app\s*=\s*(this\.wasm_create_app\(\))\s*;/g)];
  if(matches.length!==1)throw new Error('SDK diagnostic location is not unique');
  const match=matches[0],callOffset=match.index+match[0].indexOf(match[1]);
  consumerRange={start:sourceLocation(source,match.index),callStart:sourceLocation(source,callOffset),end:sourceLocation(source,callOffset+match[1].length)};
 }
 return {
  ...(consumer?{consumer:consumerRange}:{}),
  delivery:locate(/this\.exports\.wasm_network_http_response\(/g),
  finish:locate(/(?<=network_http_finish\(entry\)\s*\{\s*)if\s*\(/g),
 };
}
// Required by robrix/styles.rs HEPTA_REGULAR/HEPTA_BOLD plus app.rs's
// explicit MATH_VIEW_FONT_ASSET at the pinned Makepad revision. Packaged font
// inventory is larger than product use; observed requests cannot define coverage.
export const REQUIRED_PRODUCT_FONT_PATHS=Object.freeze([
 '/hepta_robrix_ui/resources/fonts/NotoSansSC-Regular.otf',
 '/hepta_robrix_ui/resources/fonts/NotoSansSC-Bold.otf',
 '/makepad_widgets/resources/IBMPlexSans-Text.ttf',
 '/makepad_widgets/resources/IBMPlexSans-SemiBold.ttf',
 '/makepad_widgets/resources/LXGWWenKaiRegular.ttf',
 '/makepad_widgets/resources/LXGWWenKaiBold.ttf',
 '/makepad_widgets/resources/NotoColorEmoji.ttf',
 '/makepad_widgets/resources/NewCMMath-Regular.otf',
]);
const expectedFontPaths=manifest=>Object.keys(manifest.files).filter(path=>/\.(ttf|otf)$/.test(path)).map(path=>'/'+path).sort();
export function validateDelivery(report,manifest){
 const expected=expectedFontPaths(manifest),requested=new Set(report.requests);
 if(!report.installed||report.errors.length||report.overflow) return false;
 if(!expected.length||expected.length>LIMIT||requested.size!==report.requests.length
  ||REQUIRED_PRODUCT_FONT_PATHS.some(path=>!expected.includes(path)||!requested.has(path))
  ||report.requests.some(path=>!expected.includes(path))
  ||report.records.length!==requested.size||report.finishes.length!==requested.size
  ||new Set(report.records.map(record=>record.key)).size!==requested.size)return false;
 return report.requests.every(path=>{
  const records=report.records.filter(record=>record.path===path);
  if(records.length!==1)return false;
  const record=records[0],pin=manifest.files[path.slice(1)];
  const finishes=report.finishes.filter(item=>item.key===record.key);
  return pin&&record.bytes===pin.bytes&&record.wasmBytes===pin.bytes
   &&record.sha256===pin.sha256&&record.eof===true&&finishes.length===1
   &&finishes[0].bytes===pin.bytes&&finishes[0].aborted===false;
 });
}
export async function observeFontDelivery(page,manifest){
 const session=await page.context().newCDPSession(page),scripts=new Map(),points=new Map();
 const errors=[],requests=[],sink='__heptaSdkFontDiagnostic';
 let installed=false,closed=false,instrumentation,pending=Promise.resolve(),overflow=0,setupState='idle',consumerAttempted=false;
 const breakpointEvidence=[];
 const consumerEnabled=manifest.fixtures===false,consumerNonce=consumerEnabled?randomInt(1,0x100000000):0;
 let consumerObjectId=null;
 if(consumerEnabled&&manifest.threads!==false)throw new Error('Consumer observation requires non-shared single-thread WASM');
 // The actual gateway scenario naturally draws regular Latin UI controls. Other
 // loaded/requested faces retain individual unqualified-use status in the report.
 const requiredUsePaths=['/makepad_widgets/resources/IBMPlexSans-Text.ttf'];
 const fail=error=>{if(errors.length<8)errors.push(String(error).slice(0,200));else overflow++;};
 const fontPins=Object.fromEntries(Object.entries(manifest.files).filter(([path])=>/\.(ttf|otf)$/.test(path)).map(([path,pin])=>['/'+path,pin]));
 if(Object.keys(fontPins).length>LIMIT)throw new Error('Font diagnostic catalog too large');
 const condition='entry && '+JSON.stringify(expectedFontPaths(manifest))+'.includes(new URL(entry.fetch_url).pathname)';
 await page.addInitScript(({sink})=>{window[sink]={records:[],finishes:[],overflow:0,bytes:0};},{sink});
 session.on('Debugger.scriptParsed',event=>{if(scripts.size<512)scripts.set(event.scriptId,event.url);else overflow++;});
 session.on('Debugger.paused',event=>{
  pending=pending.then(async()=>{
   try{
    const frame=event.callFrames[0],scriptId=frame?.location.scriptId;
    const point=event.hitBreakpoints?.map(id=>points.get(id)).find(Boolean),kind=point?.kind;
    if(kind==='consumer'){
     if(!installed||!consumerEnabled||consumerAttempted)throw new Error('Unexpected consumer enable boundary');
     consumerAttempted=true;
     point.evidence.pause=locationEvidence(frame.location);
     if(!sameLocation(frame.location,point.location))throw new Error('SDK consumer pause location mismatch');
     const result=await session.send('Debugger.evaluateOnCallFrame',{
      callFrameId:frame.callFrameId,silent:true,returnByValue:false,
      expression:`(()=>{
       const e=this.exports;
       for(const name of ['enable','seal','snapshot_ptr','snapshot_len'])if(typeof e['hepta_font_consumer_'+name]!=='function')throw new Error('Consumer export missing');
       if(e.hepta_font_consumer_enable(${consumerNonce})!==1)throw new Error('Consumer enable rejected nonce or reuse');
       return {exports:e,memory:this.memory};
      })()`,
     });
     if(result.exceptionDetails||!result.result?.objectId)throw new Error('Consumer enable failed');
     consumerObjectId=result.result.objectId;
    }else if(kind){
     if(consumerEnabled&&!consumerObjectId)throw new Error('SDK font delivery before consumer enable');
     const expression=kind==='delivery'?`(()=>{
      const s=window[${JSON.stringify(sink)}],path=new URL(entry.fetch_url).pathname;
      if(s.records.length>=${LIMIT}||response_body.length>64*1024*1024||s.bytes+response_body.length>${MAX_BYTES}){s.overflow++;return;}
      s.bytes+=response_body.length;
      const request=((BigInt(entry.request_id_hi>>>0)<<32n)|BigInt(entry.request_id_lo>>>0)).toString();
      const record={path,key:entry.request_key,request,bytes:response_body.length,wasmBytes:body_u8.len,eof:true};
      s.records.push(record);
      record.pending=crypto.subtle.digest('SHA-256',response_body).then(hash=>{
       record.sha256=Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join('');
      },()=>{record.hashError=true;});
     })()`:`(()=>{
      const s=window[${JSON.stringify(sink)}];
      if(s.finishes.length>=${LIMIT}){s.overflow++;return;}
      s.finishes.push({key:entry.request_key,bytes:entry.response_bytes,aborted:entry.controller.signal.aborted});
     })()`;
     const result=await session.send('Debugger.evaluateOnCallFrame',{callFrameId:frame.callFrameId,expression,silent:true});
     if(result.exceptionDetails)throw new Error('SDK diagnostic evaluation failed');
    }else if(setupState==='idle'&&scripts.get(scriptId)?.endsWith('/makepad_platform/web.js')){
     setupState='installing';
     const created=new Set(),nextPoints=new Map();
     try{
      const {scriptSource}=await session.send('Debugger.getScriptSource',{scriptId});
      if(Buffer.byteLength(scriptSource)>512*1024||sha(scriptSource)!==manifest.files['makepad_platform/web.js'].sha256)throw new Error('Served SDK source digest mismatch');
      for(const [kind,probe] of Object.entries(sdkProbeLocations(scriptSource,{consumer:consumerEnabled}))){
       const evidence={kind,requested:null,selected:null,actual:null};
       breakpointEvidence.push(evidence); // One setup attempt, at most three probes.
       let location={scriptId,...probe};
       if(kind==='consumer'){
        const start={scriptId,...probe.start},end={scriptId,...probe.end},callStart={scriptId,...probe.callStart};
        evidence.requested={start:locationEvidence(start),end:locationEvidence(end)};
        const {locations}=await session.send('Debugger.getPossibleBreakpoints',{start,end,restrictToFunction:true});
        if(!Array.isArray(locations)||locations.length>16||locations.some(value=>!validLocation(value)||value.scriptId!==scriptId
         ||positionBefore(value,start)||!positionBefore(value,end)))throw new Error('SDK consumer breakpoint range invalid');
        const calls=locations.filter(value=>value.type==='call');
        if(calls.length!==1||positionBefore(calls[0],callStart))throw new Error('SDK consumer call breakpoint is not unique');
        location=locationEvidence(calls[0]);
       }else evidence.requested=locationEvidence(location);
       evidence.selected=locationEvidence(location);
       const result=await session.send('Debugger.setBreakpoint',{location,condition:kind==='consumer'?'true':condition});
       // Retain the returned ID before validation so every partial install can roll back.
       const id=result.breakpointId,validId=typeof id==='string'&&id.length>0&&id.length<=256;
       const reused=created.has(id)||id===instrumentation;
       if(validId)created.add(id);
       evidence.actual=locationEvidence(result.actualLocation);
       if(!validId||reused)throw new Error('SDK diagnostic breakpoint ID invalid or reused');
       if(!validLocation(result.actualLocation)||result.actualLocation.scriptId!==scriptId
        ||result.actualLocation.lineNumber!==location.lineNumber||(kind==='consumer'&&!sameLocation(result.actualLocation,location)))throw new Error('SDK diagnostic breakpoint moved');
       nextPoints.set(id,{kind,location,evidence});
      }
      await session.send('Debugger.removeBreakpoint',{breakpointId:instrumentation});
      instrumentation=undefined;
      for(const [id,point]of nextPoints)points.set(id,point);
      installed=true;setupState='installed';
     }catch(error){
      setupState='failed';fail(error);
      if(instrumentation!==undefined)created.add(instrumentation);
      for(const breakpointId of created)await session.send('Debugger.removeBreakpoint',{breakpointId}).catch(error=>fail('SDK diagnostic cleanup failed: '+error));
      points.clear();
     }
    }
   }catch(error){fail(error);}
   finally{await session.send('Debugger.resume').catch(fail);}
  });
 });
 page.on('request',request=>{
  const path=new URL(request.url()).pathname;
  if(!/\.(ttf|otf|woff2?)$/i.test(path))return;
  if(!fontPins[path]){fail('Unexpected font request outside manifest allowlist');return;}
  if(requests.length<LIMIT)requests.push(path);else overflow++;
 });
 try{
  await session.send('Debugger.enable');
  ({breakpointId:instrumentation}=await session.send('Debugger.setInstrumentationBreakpoint',{instrumentation:'beforeScriptExecution'}));
 }catch(error){await session.detach();throw error;}
 async function collect(){
  await pending;
  let timer;
  try{
   const observed=await Promise.race([
    page.evaluate(async sink=>{
     const state=window[sink];if(!state)return null;
     await Promise.all(state.records.map(record=>record.pending));
     return {records:state.records.map(({pending,...record})=>record),finishes:state.finishes,overflow:state.overflow};
    },sink),
    new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('SDK diagnostic observation deadline')),3000);}),
   ]);
   if(!observed)throw new Error('SDK diagnostic page state missing');
   return {diagnosticOnly:true,scope:'actual SDK assembled bytes before WASM export plus normal finalization; font use is separate pixel/Rust evidence',installed,setupState,breakpointEvidence,errors:[...errors],requests:[...requests],...observed,overflow:overflow+observed.overflow};
  }catch(error){fail(error);return {diagnosticOnly:true,installed,setupState,breakpointEvidence,errors:[...errors],requests:[...requests],records:[],finishes:[],overflow};}
  finally{clearTimeout(timer);}
 }
 return {
  async check(){const result=await collect();if(!validateDelivery(result,manifest))throw new Error('SDK font EOF/digest/finalization diagnostic failed');},
  async close(path,{priorFailure=false}={}){
   if(closed)return;closed=true;
   try{
    const result=await collect();result.passed=validateDelivery(result,manifest);
    if(consumerEnabled){
     try{
      if(!consumerObjectId)throw new Error('Rust consumer was never enabled');
      result.consumer=await readConsumerSnapshot(session,consumerObjectId,consumerNonce);
      result.consumerValidation=validateConsumer(result.consumer,result,{nonce:consumerNonce,requiredUsePaths,manifest});
     }catch(error){result.consumerValidation={passed:false,diagnosticOnly:true,error:String(error).slice(0,512)};}
     result.passed=result.passed&&result.consumerValidation.passed;
    }
    await writeFile(path,JSON.stringify(result,null,2)+'\n');
    if(consumerEnabled)assertOptionalOutcome(result.passed,{priorFailure});
   }catch(error){if(!priorFailure)throw error;}
   finally{await session.detach().catch(()=>{});}
  },
 };
}
