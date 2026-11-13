import test from 'node:test';
import assert from 'node:assert/strict';
import {auditProductConsole} from '../tools/product-console-audit.mjs';
const runtimeUrl='http://127.0.0.1:4175/api/hepta/runtime',ownerUrl='http://127.0.0.1:4175/api/hepta/owner-status',sdkUrl='http://127.0.0.1:4175/makepad_platform/web.js';
const abort=`[makepad][http][err] GET ${ownerUrl} AbortError: signal is aborted without reason tiles=-`;
function fixture(){return {sdkUrl,runtimeUrl,ownerUrl,errors:[{url:sdkUrl,text:abort,phase:'timeout'}],requests:[{id:1,url:ownerUrl,method:'GET',phase:'timeout'}],responses:[],failures:[{id:1,url:ownerUrl,phase:'timeout',error:'net::ERR_ABORTED'}],cancellations:[{requestId:1,phase:'timeout'}],proofs:{timeout:{ownerVerified:true,ownerState:'timedOut',transportVerified:true}}};}
test('exact URL-bearing AbortError requires one failed request and verified owner state',()=>{
 assert.equal(auditProductConsole(fixture()).passed,true);
 for(const mutate of [x=>{x.failures=[];},x=>{x.proofs.timeout.ownerVerified=false;},x=>{x.proofs.timeout.ownerState='notAttached';},x=>{x.errors[0].phase='navigation';},x=>{x.errors[0].text='AbortError: signal is aborted without reason';},x=>{x.errors[0].url=runtimeUrl;},x=>{x.failures[0].id=2;}]){const x=fixture();mutate(x);assert.equal(auditProductConsole(x).passed,false);}
});
test('duplicate, unrelated and ambiguous diagnostics remain fatal',()=>{
 for(const mutate of [x=>{x.errors.push({...x.errors[0]});},x=>{x.errors.push({url:sdkUrl,text:'font missing',phase:'timeout'});},x=>{x.failures.push({id:2,url:ownerUrl,phase:'timeout',error:'net::ERR_ABORTED'});}]){const x=fixture();mutate(x);assert.equal(auditProductConsole(x).passed,false);}
 const x=fixture();x.cancellations.push({requestId:2,phase:'navigation'});assert.throws(()=>auditProductConsole(x),/one cancellation/);
});
test('503 diagnostics consume only a completed exact response with visible Transport state',()=>{
 const x=fixture();x.errors=[{url:sdkUrl,text:`[makepad][http][fail] 503 ${runtimeUrl}`,phase:'initial'}];x.requests=[{id:2,url:runtimeUrl,method:'GET',phase:'initial'}];x.responses=[{id:2,url:runtimeUrl,status:503,phase:'initial',finished:true}];x.failures=[];x.cancellations=[];x.proofs={initial:{transportVerified:true}};
 assert.equal(auditProductConsole(x).passed,true);
 const paired=structuredClone(x);paired.errors.push({url:runtimeUrl,text:'Failed to load resource: the server responded with a status of 503 (Service Unavailable)',phase:'initial'});assert.equal(auditProductConsole(paired).accepted.length,2);assert.equal(auditProductConsole(paired).passed,true);
 for(const mutate of [y=>{y.responses[0].status=500;},y=>{y.responses[0].finished=false;},y=>{y.proofs.initial.transportVerified=false;},y=>{y.errors[0].phase='timeout';},y=>{y.responses.push({...y.responses[0],id:3});},y=>{y.errors.push({...y.errors[0]});}]){const y=structuredClone(x);mutate(y);assert.equal(auditProductConsole(y).passed,false);}
});
test('asset truncation and a foreign AbortError cannot be explained by API state',()=>{
 const x=fixture();for(const error of [{url:'http://127.0.0.1:4175/font.otf',text:'Failed to load resource: net::ERR_CONTENT_LENGTH_MISMATCH',phase:'timeout'},{url:sdkUrl,text:abort.replace(ownerUrl,'http://foreign.invalid/api/hepta/owner-status'),phase:'timeout'}]){x.errors=[error];assert.equal(auditProductConsole(x).passed,false);}
});


test('a declared cancellation must be proved even when there are no diagnostics',()=>{
 const x=fixture();x.errors=[];x.failures=[];
 const result=auditProductConsole(x);assert.equal(result.passed,false);assert.equal(result.unprovedCancellations.length,1);
});
