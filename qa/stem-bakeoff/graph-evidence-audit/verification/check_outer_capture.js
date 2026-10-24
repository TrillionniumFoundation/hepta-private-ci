// Local targeted metadata verification only. No tools, original inputs or model.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require("node:path").join(__dirname,"../graph_actual_cost_recipe.js"),"utf8");
function fixture() {
  const values=new Map();let clock=1000,calls=0;
  const copy=v=>v===undefined?undefined:JSON.parse(JSON.stringify(v));
  const store=(k,v)=>values.set(k,copy(v)),load=k=>copy(values.get(k)),now=()=>++clock;
  const api=vm.runInNewContext(source,{Date:{now},store,load});
  const adapter={storePrefix:"fixture:",getState:()=>({raw_count:9}),
    runNextGraph:async(id,body)=>{calls++;return body(id);},
    runRecovery:async(id,body)=>{calls++;return body(id);}};
  const owner=id=>({graph_id:id,status:"completed",started_ms:now(),completed_ms:now(),critical_path_ms:1,collect_path_ms:1,reducer_service_path_ms:0});
  return {values,store,load,now,api,adapter,owner,calls:()=>calls};
}
let passed=0;
async function test(name,body){await body();passed++;console.log("PASS "+name);}
(async()=>{
  await test("first success has preawait intent; duplicate refuses without action or overwrite",async()=>{
    const f=fixture();const result=await f.api.graph(f.adapter,"b0-A",async id=>{
      assert.equal(f.load("fixture:outer:graph:b0-A").capture_status,"pending");return f.owner(id);
    });
    const original=JSON.stringify(f.load("fixture:outer:graph:b0-A"));
    assert.equal(JSON.parse(original).capture_status,"returned");assert.equal(JSON.parse(original).original_owner_completed_ms,result.completed_ms);
    await assert.rejects(()=>f.api.graph(f.adapter,"b0-A",f.owner),/already recorded/);
    assert.equal(f.calls(),1);assert.equal(JSON.stringify(f.load("fixture:outer:graph:b0-A")),original);
  });
  await test("pending duplicate is blocked before original resolves and leaves its intent unchanged",async()=>{
    const f=fixture();let release;
    const first=f.api.graph(f.adapter,"b0-A",id=>new Promise(resolve=>{release=()=>resolve(f.owner(id));}));
    const pending=JSON.stringify(f.load("fixture:outer:graph:b0-A"));
    await assert.rejects(()=>f.api.graph(f.adapter,"b0-A",f.owner),/already recorded/);
    assert.equal(JSON.stringify(f.load("fixture:outer:graph:b0-A")),pending);assert.equal(f.calls(),1);
    release();await first;assert.equal(f.load("fixture:outer:graph:b0-A").capture_status,"returned");
  });
  await test("publication throw retains original owner and same thrown error; repeat cannot overwrite",async()=>{
    const f=fixture(),failure=new Error("fixture publication failed");let retained;
    await assert.rejects(()=>f.api.graph(f.adapter,"b0-A",async id=>{retained=f.owner(id);f.store("fixture:owner:"+id,retained);throw failure;}),error=>error===failure);
    const saved=f.load("fixture:outer:graph:b0-A"),bytes=JSON.stringify(saved);
    assert.equal(saved.capture_status,"threw");assert.equal(saved.returned,false);assert.equal(saved.original_owner_completed_ms,retained.completed_ms);assert.equal(saved.original_owner_source,"session_store_after_unreturned_owner");
    await assert.rejects(()=>f.api.graph(f.adapter,"b0-A",f.owner),/already recorded/);assert.equal(f.calls(),1);assert.equal(JSON.stringify(f.load("fixture:outer:graph:b0-A")),bytes);
  });
  await test("early throw keeps unknown original times null rather than zero",async()=>{
    const f=fixture();await assert.rejects(()=>f.api.graph(f.adapter,"b0-A",async()=>{throw new Error("before owner");}));
    const saved=f.load("fixture:outer:graph:b0-A");for(const key of ["original_owner_started_ms","original_owner_completed_ms","original_graph_critical_path_ms","after_original_owner_ms"])assert.equal(saved[key],null);
  });
  await test("recovery uses exact original start/end fields and rejects repeated outer invocation",async()=>{
    const f=fixture();const result=await f.api.recovery(f.adapter,"b0-A-s0",async id=>({request_id:id,status:"completed",started_ms:f.now(),completed_ms:f.now()}));
    const saved=f.load("fixture:outer:recovery:b0-A-s0");assert.equal(saved.original_recovery_elapsed_ms,result.completed_ms-result.started_ms);assert.equal(saved.original_graph_critical_path_ms,null);
    await assert.rejects(()=>f.api.recovery(f.adapter,"b0-A-s0",async()=>{}),/already recorded/);assert.equal(f.calls(),1);
  });
  await test("first flush records preawait intent; duplicate cannot invoke or overwrite",async()=>{
    const f=fixture();let calls=0;f.adapter.flushRawLedger=async()=>{calls++;assert.equal(f.load("fixture:outer:ledger").capture_status,"pending");return {snapshot_record_count:9};};
    await f.api.flush(f.adapter);const original=JSON.stringify(f.load("fixture:outer:ledger"));
    await assert.rejects(()=>f.api.flush(f.adapter),/already recorded/);assert.equal(calls,1);assert.equal(JSON.stringify(f.load("fixture:outer:ledger")),original);
  });
  await test("failed flush stays failed with original null publication and is never repeated",async()=>{
    const f=fixture();let calls=0;f.adapter.flushRawLedger=async()=>{calls++;throw new Error("fixture flush failed");};
    await assert.rejects(()=>f.api.flush(f.adapter),/flush failed/);const original=JSON.stringify(f.load("fixture:outer:ledger"));
    assert.equal(JSON.parse(original).capture_status,"threw");assert.equal(JSON.parse(original).returned_publication_receipt,null);
    await assert.rejects(()=>f.api.flush(f.adapter),/already recorded/);assert.equal(calls,1);assert.equal(JSON.stringify(f.load("fixture:outer:ledger")),original);
  });
  console.log(JSON.stringify({passed,native_calls:0,scope:"targeted local metadata tests only; no graph/model/original input execution"}));
})().catch(error=>{console.error(error);process.exitCode=1;});
