// Test evidence only. Exact SDK diagnostics must have an unambiguous captured
// request witness; an active cancellation phase alone never excuses an error.
import assert from 'node:assert/strict';
export function auditProductConsole({errors,requests,responses,failures,cancellations,proofs,sdkUrl,runtimeUrl,ownerUrl}){
 const byId=new Map(requests.map(r=>[r.id,r]));
 assert.equal(byId.size,requests.length,'Duplicate captured request identity');
 assert.ok(requests.every(r=>Number.isSafeInteger(r.id)&&r.id>0));
 assert.ok(cancellations.length<=1,'Each fresh page may prove only one cancellation');
 const used=new Set(),accepted=[],unexpected=[];
 const unexpectedRecords=[...responses,...failures].filter(r=>!byId.has(r.id)||byId.get(r.id).url!==r.url||byId.get(r.id).phase!==r.phase);
 const cancelledRequest=()=>{
  if(cancellations.length!==1)return null;
  const c=cancellations[0],r=byId.get(c.requestId),proof=proofs[c.phase];
  const expectedState=c.phase==='timeout'?'timedOut':['navigation','background'].includes(c.phase)?'noObservation':null;
  if(!r||r.url!==ownerUrl||r.method!=='GET'||r.phase!==c.phase||!expectedState||proof?.ownerVerified!==true||proof.ownerState!==expectedState)return null;
  const failed=failures.filter(f=>f.url===ownerUrl);
  if(failed.length!==1||failed[0].id!==r.id||failed[0].phase!==r.phase||!['net::ERR_ABORTED','net::ERR_FAILED'].includes(failed[0].error))return null;
  return r;
 };
 for(const error of errors){
  let witness=null,kind=null;
  const sdk503=error.url===sdkUrl&&error.text===`[makepad][http][fail] 503 ${runtimeUrl}`;
  const browser503=error.url===runtimeUrl&&/^Failed to load resource: the server responded with a status of 503(?: \(Service Unavailable\))?$/.test(error.text);
  if(sdk503||browser503){
   const candidates=responses.filter(r=>r.url===runtimeUrl&&r.status===503&&r.phase===error.phase&&r.finished===true&&byId.get(r.id)?.url===runtimeUrl&&byId.get(r.id)?.phase===r.phase&&byId.get(r.id)?.method==='GET');
   if(candidates.length===1&&proofs[error.phase]?.transportVerified===true){witness=candidates[0];kind=sdk503?'sdk-503':'browser-503';}
  }else if(error.url===sdkUrl&&error.text===`[makepad][http][err] GET ${ownerUrl} AbortError: signal is aborted without reason tiles=-`){
   const request=cancelledRequest();
   if(request&&request.phase===error.phase){witness=request;kind='sdk-abort';}
  }
  const key=witness?`${kind}:${witness.id}`:null;
  if(!key||used.has(key))unexpected.push(error);
  else{used.add(key);accepted.push({kind,requestId:witness.id,error});}
 }
 const cancellation=cancelledRequest();
 const unprovedCancellations=cancellations.length&&!cancellation?[...cancellations]:[];
 const unexpectedFailures=failures.filter(f=>!cancellation||f.id!==cancellation.id||f.url!==ownerUrl||f.phase!==cancellation.phase||!['net::ERR_ABORTED','net::ERR_FAILED'].includes(f.error));
 return {passed:unexpected.length===0&&unexpectedFailures.length===0&&unexpectedRecords.length===0&&unprovedCancellations.length===0,accepted,unexpected,unexpectedFailures,unexpectedRecords,unprovedCancellations};
}
