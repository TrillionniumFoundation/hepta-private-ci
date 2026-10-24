/* Independent byte vectors + synthetic original-tool contract tests only.
 * No original graph/head/feature input and no native host call is used.
 */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const nodeHash = text => crypto.createHash("sha256").update(text).digest("hex");
const helperSource = fs.readFileSync(path.join(__dirname,"cell_graph_native_helpers.js"),"utf8");
const adapterSource = fs.readFileSync(path.join(__dirname,"cell_graph_native_adapter.js"),"utf8");
const ownerPath = fs.existsSync(path.join(__dirname,"cell_graph_owner.js")) ? path.join(__dirname,"cell_graph_owner.js") : path.join(__dirname,"../patch/qa/stem-bakeoff/cell_graph_owner.js");
const ownerSource = fs.readFileSync(ownerPath,"utf8");
assert.equal(nodeHash(ownerSource),"a8f1e561f3bff60b0247351c27619a874403006cd44ee40035b2cc3c8a1de112");
const context = vm.createContext({setTimeout:callback=>{callback();return 0;}});
vm.runInContext(helperSource+"\n"+adapterSource+"\n"+ownerSource+"\nglobalThis.testAPI={B:CellGraphBytes,create:createCellGraphNativeAdapter,execute:executeCellGraph,recover:recoverCellGraphNode};",context);
const {B,create,execute,recover}=context.testAPI;
const plain=value=>JSON.parse(JSON.stringify(value));
let passed=0;
async function test(name,fn){await fn();passed++;console.log("PASS "+name);}

function fixture() {
  const protocol="2c88c2a47f56c05ea86f221ad26806fb5190bd17b8b32a9284a0ae31dfbe85e5", graphSha="a".repeat(64);
  const graphs=[], texts={}, orders=["ABC","ACB","BAC","BCA","CAB","CBA"];
  for(let block=0;block<6;block++) for(const arm of orders[block]) {
    const graph={graph_id:`b${block}-${arm}`,block,arm,requests:[]};
    for(let shard=0;shard<(arm==="A"?1:2);shard++) {
      const id=graph.graph_id+`-s${shard}`,host=arm==="C"&&shard===block%2?"pocket4":"main";
      const cpu=arm==="A"?200:100,mem=arm==="A"?2147483648:1073741824,indices=arm==="A"?[0,1,2,3,4,5]:[[0,3,4],[1,2,5]][shard];
      const body={schema:"hepta.fixed-cell-graph.worker.v1",authority:"DENY_ALL",request_id:id,protocol_sha256:protocol,graph_sha256:graphSha,environment_sha256:(host==="main"?"b":"c").repeat(64),head_indices:indices,resource_limits:{cpu_quota_percent:cpu,memory_max_bytes:mem},features:{fixture:"no original data"},heads:[]};
      texts[id]=JSON.stringify(body)+"\n";
      graph.requests.push({request_id:id,host,request_file:id+".json",request_sha256:nodeHash(texts[id]),request_bytes:Buffer.byteLength(texts[id]),head_indices:indices,idempotency_key:`cell-graph-v1-${graphSha.slice(0,16)}-${id}`,python_executable:host==="main"?"/data/hepta-cell-input-20261024/.venv/bin/python":"/usr/bin/python3",cpu_quota_percent:cpu,memory_max_bytes:mem,wall_seconds:45,cpu_seconds:10,max_stdout_bytes:196608,max_stderr_bytes:8192,worker_source_sha256:"bb9a6ddc30cc267d22a530e9486e6590cdef15247d1546905b4a051e8eed8358",environment_sha256:body.environment_sha256});
    }
    graphs.push(graph);
  }
  const plan={schema:"hepta.fixed-cell-graph.dispatch.v1",protocol_sha256:protocol,graph_sha256:graphSha,requests:30,graphs};
  const dispatchText=JSON.stringify(plan)+"\n";
  return {dispatch_text:dispatchText,dispatch_sha256:nodeHash(dispatchText),request_text_by_id:texts,wrapper_sha256:"d".repeat(64)};
}
function fakeBackend(options={}) {
  const jobs=new Map(), byId=new Map(), calls=[], publications=[]; let sequence=0;
  function mcp(value) {return {content:[{type:"text",text:JSON.stringify(value).replace('"EXACT_U64"',"17472191996759269219")}],structuredContent:null,isError:false};}
  function response(job,reused){return mcp({audit_recorded:true,reused,local_record_pending:false,launch:{ok:true,backend:"systemd"},job:{id:job.id,host:job.args.host,idempotency_key:job.args.idempotency_key,executable:job.args.executable,args:job.args.args,cwd:job.args.cwd,env_keys:Object.keys(job.args.env),request_digest:options.rebindRecovery&&reused?"e".repeat(64):nodeHash(JSON.stringify(job.args)),request_fingerprint:"EXACT_U64",launch_state:"launched",launch_error:null}});}
  const tools={};
  tools.mcp__codex_apps__hepta_runtime_full_operator_process_start=async args=>{
    calls.push({operation:"start",args:plain(args)});
    const key=args.host+":"+args.idempotency_key;
    if(jobs.has(key))return response(jobs.get(key),true);
    const input=JSON.parse(args.stdin),worker=input.schema==="hepta.fixed-cell-graph.worker.v1";
    let output;
    if(worker) output=options.workerOutput||Buffer.from("synthetic transport bytes:\u4e2d\ud83e\udd16\nfixture only\n");
    else {
      const result={schema:"hepta.fixed-cell-graph.native-wrapper-result.v1",operation:input.operation,dispatch_sha256:input.dispatch_sha256,wrapper_sha256:input.expected_wrapper_sha256,wrapper_cost:{synthetic:true}};
      if(input.graph_id)result.graph_id=input.graph_id;
      if(input.collection)result.collection_sha256=input.collection.sha256;
      if(input.owner)result.owner_sha256=input.owner.sha256;
      if(input.record){result.request_id=input.request_id;result.record_sha256=input.record.sha256;}
      if(input.operation==="raw_chunk"){result.index=input.index;result.chunk_sha256=input.chunk.sha256;}
      if(input.operation==="raw_seal"){result.ledger_sha256=input.ledger_sha256;result.ledger_bytes=input.ledger_bytes;}
      if(input.operation==="reduce") {
        const collection=JSON.parse(Buffer.from(input.collection.base64,"base64"));
        result.reduction={graph_id:input.graph_id,status:collection.workers.every(w=>w.status==="completed")?"completed":"failed",receipt_sha256:"f".repeat(64)};
      }
      if(input.operation==="publish"||input.operation==="recovery")publications.push(input);
      output=Buffer.from(JSON.stringify(result)+"\n");
    }
    const job={id:"fixture-job-"+(++sequence),args:plain(args),output,stderr:worker?(options.stderr||Buffer.alloc(0)):Buffer.alloc(0),worker};
    jobs.set(key,job);byId.set(job.id,job);
    if((options.unknownWorkerStart&&worker)||(options.unknownReducerStart&&!worker&&input.operation==="reduce"))throw new Error("synthetic transport failure after real start could have occurred");
    // Deliberately yield so concurrent primary submissions must both be made.
    await Promise.resolve();
    return response(job,worker&&Boolean(options.primaryReused));
  };
  tools.mcp__codex_apps__hepta_runtime_full_operator_process_status=async args=>{
    calls.push({operation:"status",args:plain(args)});const job=byId.get(args.job_id);assert.equal(job.args.host,args.host);
    if(options.running&&job.worker)return mcp({audit_recorded:true,job_id:job.id,state:"running",systemd:{ExecMainStatus:"0"}});
    return mcp({audit_recorded:true,job_id:job.id,state:options.failed&&job.worker?"failed":"succeeded",exit_code:options.failed&&job.worker?7:0,timed_out:false,cancelled:false,output_complete:true,log_bytes:{stdout:{seen:job.output.length,stored:job.output.length},stderr:{seen:job.stderr.length,stored:job.stderr.length}},log_errors:{stdout:null,stderr:null},log_truncated:{stdout:Boolean(options.truncated&&job.worker),stderr:false}});
  };
  tools.mcp__codex_apps__hepta_runtime_full_operator_process_read=async args=>{
    calls.push({operation:"read",args:plain(args)});const job=byId.get(args.job_id);assert.equal(args.limit,16384);
    function stream(data,offset){const part=data.subarray(offset,offset+args.limit);return {bytes_hex:part.toString("hex"),text:"deliberately unusable lossy display",offset:offset+(options.hole&&job.worker?1:0),next_offset:offset+part.length,size:data.length,eof:offset+part.length===data.length};}
    return mcp({audit_recorded:true,job_id:job.id,stdout:stream(job.output,args.stdout_offset),stderr:stream(job.stderr,args.stderr_offset)});
  };
  return {tools,jobs,byId,calls,publications};
}
function setup(options={}){
  const input=fixture(), backend=fakeBackend(options), values=new Map();
  const adapter=create({tools:backend.tools,store:(key,value)=>values.set(key,plain(value)),load:key=>values.has(key)?plain(values.get(key)):undefined,inputs:input});
  return {input,backend,values,adapter};
}

(async()=>{
  await test("SHA256 standard vectors and independent Node crypto across padding boundaries",()=>{
    const vectors=[["","e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],["abc","ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],["abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq","248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"]];
    for(const [value,want] of vectors)assert.equal(B.hashText(value),want);
    for(const length of [1,2,3,55,56,63,64,65,127,128,129,4096,16384,65537]){const data=Buffer.from(Array.from({length},(_,i)=>(i*73+17)%256));assert.equal(B.sha256(Array.from(data)),nodeHash(data));}
    assert.equal(B.hashText("a".repeat(1000000)),"cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
  });
  await test("UTF8 independent Buffer vectors and malformed sequence rejection",()=>{
    for(const value of ["","ASCII\u0000","中文","e\u0301","\ud83e\udd16","\u007f\u0080\u07ff\u0800\uffff\udbff\udfff"]){assert.equal(B.hex(B.utf8(value)),Buffer.from(value).toString("hex"));assert.equal(B.text(Array.from(Buffer.from(value))),value);}
    for(const value of ["\ud800","\udc00","x\ud800y"])assert.throws(()=>B.utf8(value));
    for(const value of [[0xc0,0x80],[0xed,0xa0,0x80],[0xf4,0x90,0x80,0x80],[0xe2,0x82],[0x80],[0xf0,0x80,0x80,0x80]])assert.throws(()=>B.text(value));
  });
  await test("RFC4648 base64 vectors, Node bytes oracle, canonical pad/hex rejection",()=>{
    for(const [text,want] of [["",""],["f","Zg=="],["fo","Zm8="],["foo","Zm9v"],["foob","Zm9vYg=="],["fooba","Zm9vYmE="],["foobar","Zm9vYmFy"]]){assert.equal(B.base64(Array.from(Buffer.from(text))),want);assert.equal(B.text(B.unbase64(want)),text);}
    const data=Buffer.from(Array.from({length:256},(_,i)=>i));assert.equal(B.base64(Array.from(data)),data.toString("base64"));assert.equal(B.hex(B.unbase64(data.toString("base64"))),data.toString("hex"));
    for(const bad of ["Zg=","Zg==\n","Zh==","Zm9=","===="])assert.throws(()=>B.unbase64(bad));
    for(const bad of ["0","AB","0g"])assert.throws(()=>B.unhex(bad));
  });
  await test("lossless uint64 JSON, duplicate/nonfinite/malformed rejection, actual native sample",()=>{
    const parsed=B.parseJSON('{"fingerprint":17472191996759269219,"safe":9007199254740991,"x":"escaped\\\" quote"}');
    assert.equal(parsed.fingerprint,"17472191996759269219");assert.equal(parsed.safe,9007199254740991);
    for(const bad of ['{"x":1,"x":2}','[1,]','{"x":1e999}','01','true false','"\\ud800"'])assert.throws(()=>B.parseJSON(bad));
    const sample=JSON.parse(fs.readFileSync(path.join(__dirname,"cell_graph_native_start_fixture.json"),"utf8"));
    assert.equal(B.parseJSON(sample.content[0].text).job.request_fingerprint,"17472191996759269219");
  });
  await test("V8 helpers load with no Node/browser codec globals",()=>{
    assert.equal(vm.runInContext("typeof require+','+typeof crypto+','+typeof TextEncoder+','+typeof TextDecoder+','+typeof atob+','+typeof btoa+','+typeof performance",context),"undefined,undefined,undefined,undefined,undefined,undefined,undefined");
  });
  await test("tampered input/resources reject before any native call",()=>{
    const input=fixture(), backend=fakeBackend();input.request_text_by_id["b0-A-s0"]+=" ";
    assert.throws(()=>create({tools:backend.tools,store:()=>{},load:()=>undefined,inputs:input}));assert.equal(backend.calls.length,0);
  });
  await test("maximum12-page stdout and exact stderr bytes survive lossy text display",async()=>{
    const output=Buffer.alloc(196608);for(let i=0;i<output.length;i++)output[i]=(i*17)%256;
    const stderr=Buffer.from([0,255,194,128]);const {adapter,backend,values}=setup({workerOutput:output,stderr});
    const owner=await adapter.runNextGraph("b0-A",execute);assert.equal(owner.status,"completed");
    const worker=values.get(adapter.storePrefix+"collection:b0-A").workers[0];
    assert.equal(worker.stdout_sha256,nodeHash(output));assert.equal(worker.stdout_base64,output.toString("base64"));assert.equal(worker.stderr_base64,stderr.toString("base64"));assert.equal(worker.read_pages,12);assert.equal(worker.native_request_fingerprint,"17472191996759269219");
    assert.equal(owner.events.filter(e=>e.operation==="process_read").length,12);assert.equal(owner.events.length,15);
    assert.equal(backend.calls.filter(c=>c.operation==="read"&&c.args.job_id===worker.job_id).length,12);
  });
  await test("all18 ordered graphs, concurrent shards, raw provenance, three exact reused jobs",async()=>{
    const {adapter,backend,values}=setup();
    for(const graph of adapter.dispatch.graphs){const owner=await adapter.runNextGraph(graph.graph_id,execute);assert.equal(owner.status,"completed");assert.equal(owner.concurrent_start_calls_observed,true);}
    assert.equal(Array.from(backend.jobs.values()).filter(j=>j.worker).length,30);
    for(const request of ["b0-A-s0","b0-B-s0","b0-C-s0"]){const result=await adapter.runRecovery(request,recover);assert.equal(result.status,"completed");assert.equal(result.collection.start_disposition,"reused");}
    assert.equal(Array.from(backend.jobs.values()).filter(j=>j.worker).length,30);
    await assert.rejects(()=>adapter.runNextGraph("b0-A",execute));
    const snapshot=adapter.snapshotRaw();assert.equal(snapshot.sha256,nodeHash(Buffer.from(snapshot.data)));assert.ok(snapshot.record_count>200);
    const ledger=JSON.parse(Buffer.from(snapshot.data));assert.ok(ledger.records.some(r=>r.result_json.includes("17472191996759269219")));
    for(const record of ledger.records){assert.equal(record.arguments_sha256,nodeHash(record.arguments_json));if(record.result_json)assert.equal(record.native_receipt_sha256,nodeHash(record.result_json));}
    assert.equal(adapter.getState().next_graph,18);assert.equal(values.get(adapter.storePrefix+"owner:b0-C").events.filter(e=>e.operation==="process_start").length,2);
  });
  await test("reused primary is retained as failed and never replaced",async()=>{
    const {adapter,backend,values}=setup({primaryReused:true});const owner=await adapter.runNextGraph("b0-A",execute);
    assert.equal(owner.status,"failed");assert.equal(values.get(adapter.storePrefix+"collection:b0-A").workers[0].start_disposition,"reused");
    assert.equal(backend.calls.filter(c=>c.operation==="start"&&c.args.args.includes("--expected-request-sha256")).length,1);assert.equal(owner.cleanup_events.length,0);
  });
  await test("read hole fails with instrumented status-only cleanup and preserved raw page",async()=>{
    const {adapter,values}=setup({hole:true});const owner=await adapter.runNextGraph("b0-A",execute);
    assert.equal(owner.status,"failed");assert.equal(owner.cleanup_events.length,1);assert.equal(owner.cleanup_events[0].operation,"process_status");
    assert.equal(values.get(adapter.storePrefix+"collection:b0-A").workers[0].cleanup.result.termination_acknowledged,false);
    assert.ok(adapter.snapshotRaw().record_count>5);
  });
  await test("terminal truncation and oversized stdout cannot qualify",async()=>{
    for(const options of [{truncated:true},{workerOutput:Buffer.alloc(196609)}]){const {adapter}=setup(options);const owner=await adapter.runNextGraph("b0-A",execute);assert.equal(owner.status,"failed");assert.equal(owner.cleanup_events.length,1);}
  });
  await test("authoritative failed exit stays failed with known output and unknown process cost",async()=>{
    const {adapter,values}=setup({failed:true});const owner=await adapter.runNextGraph("b0-A",execute);assert.equal(owner.status,"failed");
    const node=values.get(adapter.storePrefix+"collection:b0-A").workers[0];assert.equal(node.exit_code,7);assert.equal(node.stdout_complete,true);assert.equal(node.native_process_cpu_ns,null);
  });
  await test("running systemd ExecMainStatus0 never means successful completion",async()=>{
    const {adapter}=setup({running:true});const owner=await adapter.runNextGraph("b0-A",execute);assert.equal(owner.status,"failed");assert.equal(owner.events.filter(e=>e.operation==="process_status").length,10);assert.equal(owner.cleanup_events.length,1);
    assert.equal(Object.keys(adapter.getState().outstanding).length,1);await assert.rejects(()=>adapter.runNextGraph("b0-B",execute),/outstanding/);
  });
  await test("recovery before census rejected and changed native digest never admitted",async()=>{
    const {adapter}=setup({rebindRecovery:true});await assert.rejects(()=>adapter.runRecovery("b0-A-s0",recover));
    for(const graph of adapter.dispatch.graphs)await adapter.runNextGraph(graph.graph_id,execute);
    const result=await adapter.runRecovery("b0-A-s0",recover);assert.equal(result.status,"failed");assert.equal(result.api_events.length,1);assert.equal(result.api_events[0].status,"failed");
  });
  await test("fresh V8 adapter reconstruction retains exact next graph and records repeated setup",async()=>{
    const {input,backend,values,adapter}=setup();await adapter.runNextGraph("b0-A",execute);
    const reconstructed=create({tools:backend.tools,store:(key,value)=>values.set(key,plain(value)),load:key=>values.has(key)?plain(values.get(key)):undefined,inputs:input});
    assert.equal(reconstructed.getState().next_graph,1);assert.equal(reconstructed.getState().construction_count,2);
    assert.equal((await reconstructed.runNextGraph("b0-B",execute)).status,"completed");
    assert.equal(JSON.parse(Buffer.from(reconstructed.snapshotRaw().data)).constructions.length,2);
  });
  await test("raw ledger over1MiB uses exact bounded chunks and separates future sealing calls",async()=>{
    const {adapter,backend}=setup({workerOutput:Buffer.alloc(196608,65)});await adapter.runNextGraph("b0-A",execute);
    const previousCount=adapter.getState().raw_count;
    const result=await adapter.flushRawLedger();assert.ok(result.ledger_bytes>1048576);assert.equal(result.snapshot_record_count,previousCount);assert.equal(result.snapshot_excludes_own_future_sealing_calls,true);assert.ok(adapter.getState().raw_count>previousCount);
    const chunks=backend.calls.filter(c=>c.operation==="start"&&JSON.parse(c.args.stdin).operation==="raw_chunk");assert.ok(chunks.length>=3);
    const reassembled=Buffer.concat(chunks.map(c=>Buffer.from(JSON.parse(c.args.stdin).chunk.base64,"base64")));
    assert.equal(nodeHash(reassembled),result.ledger_sha256);
    for(const c of chunks)assert.ok(Buffer.byteLength(c.args.stdin)<=1048576);
  });
  await test("unacknowledged worker or reducer start blocks every subsequent graph",async()=>{
    for(const options of [{unknownWorkerStart:true},{unknownReducerStart:true}]){
      const {adapter,backend}=setup(options);const owner=await adapter.runNextGraph("b0-A",execute);assert.equal(owner.status,"failed");
      const outstanding=Object.values(adapter.getState().outstanding);assert.equal(outstanding.length,1);assert.equal(outstanding[0].job_id,null);assert.equal(outstanding[0].status,"start_attempted_outcome_unknown");
      const count=backend.calls.length;await assert.rejects(()=>adapter.runNextGraph("b0-B",execute),/outstanding/);assert.equal(backend.calls.length,count);
    }
  });
  await test("definitive failed terminal clears process overlap gate without making task success",async()=>{
    const {adapter}=setup({failed:true});assert.equal((await adapter.runNextGraph("b0-A",execute)).status,"failed");assert.equal(Object.keys(adapter.getState().outstanding).length,0);
    assert.equal((await adapter.runNextGraph("b0-B",execute)).status,"failed");assert.equal(Object.keys(adapter.getState().outstanding).length,0);
  });
  console.log(JSON.stringify({passed,scope:"pure local synthetic transport fixtures; no native jobs, original parameters, model runs or benchmark qualification"}));
})().catch(error=>{console.error(error);process.exitCode=1;});
