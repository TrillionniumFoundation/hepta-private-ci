/* Actual original Runtime adapter. Evaluate after cell_graph_native_helpers.js.
 * No host is contacted at construction. Owner computation source stays frozen.
 */
function createCellGraphNativeAdapter({tools, store, load, inputs}) {
  const constructionStarted = Date.now();
  const B = CellGraphBytes, check = B.requireValue;
  const PROTOCOL = "2c88c2a47f56c05ea86f221ad26806fb5190bd17b8b32a9284a0ae31dfbe85e5";
  const WORKER = "bb9a6ddc30cc267d22a530e9486e6590cdef15247d1546905b4a051e8eed8358";
  const MAIN = "/home/qian-qi/workspace/hepta-cell-graph-evidence-20261024";
  const WORKTREE = "/home/qian-qi/workspace/hepta-cell-graph-benchmark-20261024";
  const PYTHON = {main:"/data/hepta-cell-input-20261024/.venv/bin/python", pocket4:"/usr/bin/python3"};
  const WORKER_PATH = {main: MAIN + "/worker/cell_graph_worker.py", pocket4:"/home/alex/hepta-cell-graph-evidence-20261024/worker/cell_graph_worker.py"};
  const WRAPPER = WORKTREE + "/qa/stem-bakeoff/cell_graph_native_wrapper.py";
  const ENV = {OPENBLAS_NUM_THREADS:"1",OMP_NUM_THREADS:"1",MKL_NUM_THREADS:"1",CUDA_VISIBLE_DEVICES:""};
  const TOOLS = {process_start:"mcp__codex_apps__hepta_runtime_full_operator_process_start", process_status:"mcp__codex_apps__hepta_runtime_full_operator_process_status", process_read:"mcp__codex_apps__hepta_runtime_full_operator_process_read"};
  const isSha = x => typeof x === "string" && /^[0-9a-f]{64}$/.test(x);
  const equal = (a,b) => B.json(a) === B.json(b);
  const clone = value => B.parseJSON(B.json(value));
  const size = value => B.utf8(value).length;
  check(typeof store === "function" && typeof load === "function", "session-retained functions store/load bindings required");
  check(isSha(inputs.dispatch_sha256) && B.hashText(inputs.dispatch_text) === inputs.dispatch_sha256, "exact dispatch bytes required");
  check(isSha(inputs.wrapper_sha256), "pre-frozen wrapper SHA required");
  const dispatch = B.parseJSON(inputs.dispatch_text), dispatchSha = inputs.dispatch_sha256;
  check(dispatch.schema === "hepta.fixed-cell-graph.dispatch.v1" && dispatch.protocol_sha256 === PROTOCOL && dispatch.requests === 30 && dispatch.graphs.length === 18 && isSha(dispatch.graph_sha256), "frozen18-graph/30-worker protocol required");
  const orders = ["ABC","ACB","BAC","BCA","CAB","CBA"], requests = Object.create(null), texts = Object.create(null);
  const shards = [[0,3,4],[1,2,5]];
  dispatch.graphs.forEach((graph,index) => {
    const block = Math.floor(index/3), arm = orders[block][index%3], graphId = `b${block}-${arm}`;
    check(graph.graph_id === graphId && graph.block === block && graph.arm === arm && graph.requests.length === (arm === "A" ? 1 : 2), "exact predeclared graph order/census required");
    graph.requests.forEach((request,shard) => {
      const id = graphId + `-s${shard}`, host = arm === "C" && shard === block%2 ? "pocket4" : "main";
      const cpu = arm === "A" ? 200 : 100, memory = arm === "A" ? 2147483648 : 1073741824;
      check(request.request_id === id && request.host === host && request.python_executable === PYTHON[host] && request.cpu_quota_percent === cpu && request.memory_max_bytes === memory && request.wall_seconds === 45 && request.cpu_seconds === 10 && request.max_stdout_bytes === 196608 && request.max_stderr_bytes === 8192 && request.worker_source_sha256 === WORKER && isSha(request.environment_sha256) && equal(request.head_indices,arm === "A" ? [0,1,2,3,4,5] : shards[shard]) && request.idempotency_key === `cell-graph-v1-${dispatch.graph_sha256.slice(0,16)}-${id}`, "fixed worker binding/resources/identity differ");
      const source = inputs.request_text_by_id[id];
      check(typeof source === "string" && size(source) <= 1048576 && size(source) === request.request_bytes && B.hashText(source) === request.request_sha256, "exact bounded native stdin required");
      const body = B.parseJSON(source);
      check(body.schema === "hepta.fixed-cell-graph.worker.v1" && body.authority === "DENY_ALL" && body.request_id === id && body.graph_sha256 === dispatch.graph_sha256 && body.protocol_sha256 === PROTOCOL && body.environment_sha256 === request.environment_sha256 && equal(body.head_indices,request.head_indices) && body.resource_limits.cpu_quota_percent === cpu && body.resource_limits.memory_max_bytes === memory, "stdin and frozen dispatch differ");
      requests[id] = clone(request); texts[id] = source;
    });
  });
  check(Object.keys(inputs.request_text_by_id).length === 30, "exact30 stdin entries required");
  const prefix = "cell-graph-native:" + dispatchSha + ":";
  function get(key) { return load(prefix + key); }
  function put(key,value) { store(prefix + key,value); }
  let state = get("state");
  if (!state) {
    state = {schema:"hepta.fixed-cell-graph.native-state.v1",dispatch_sha256:dispatchSha,wrapper_sha256:inputs.wrapper_sha256,next_graph:0,active:null,recoveries:[],raw_count:0,construction_count:0,outstanding:{},settlements:{}};
    put("state",state); put("dispatch_text",inputs.dispatch_text);
  }
  check(state.dispatch_sha256 === dispatchSha && state.wrapper_sha256 === inputs.wrapper_sha256 && get("dispatch_text") === inputs.dispatch_text, "existing run state belongs to different frozen inputs");
  function setState(next) { put("state",next); return next; }
  function checkedRequest(request) {
    const expected = requests[request.request_id]; check(expected && equal(expected,request), "request differs from frozen dispatch"); return expected;
  }
  function exactNativeResult(result) {
    check(result && result.isError === false && Array.isArray(result.content) && result.content.length === 1 && result.content[0].type === "text" && typeof result.content[0].text === "string", "one exact native JSON text receipt required");
    const parsed = B.parseJSON(result.content[0].text);
    check(parsed && parsed.audit_recorded === true, "authoritative native audit receipt required"); return parsed;
  }
  async function native(operation,args,lane,requestId) {
    const actual = clone(args), argumentText = B.json(actual);
    const current = get("state"), index = current.raw_count;
    const pendingKey = operation === "process_start" ? lane+":"+requestId : null;
    if (pendingKey) {
      check(!current.outstanding[pendingKey], "original launch remains outstanding; no start retry");
      current.outstanding[pendingKey]={host:args.host,request_id:requestId,lane,job_id:null,arguments_sha256:B.hashText(argumentText),status:"start_attempted_outcome_unknown",started_ms:Date.now()};
    }
    current.raw_count++;
    setState(current);
    const key = "raw:" + String(index).padStart(6,"0");
    const record = {schema:"hepta.fixed-cell-graph.native-call.v1",index,lane,operation,request_id:requestId,arguments_json:argumentText,arguments_sha256:B.hashText(argumentText),logical_tool_request_bytes:size(argumentText),started_ms:Date.now(),status:"pending",timing_scope:"API await after argument serialization, ending before raw hashing/parsing; enclosing frozen-owner event also includes adapter work. Never add nested spans."};
    put(key,record);
    try {
      const result = await tools[TOOLS[operation]](actual);
      // Preserve exact MCP text (including unsafe integer lexemes) before parsing.
      const raw = B.json(result);
      record.finished_ms = Date.now(); record.elapsed_ms = record.finished_ms - record.started_ms;
      record.result_json = raw; record.native_receipt_sha256 = B.hashText(raw); record.logical_tool_response_bytes = size(raw); record.status = "returned"; put(key,record);
      const parsed = exactNativeResult(result);
      // A definitively ended original process can release sequential admission
      // even if output later fails qualification or the owner's await was late.
      // Missing job identity, running state, or transport failure never does so.
      if (operation === "process_status" && parsed.job_id === args.job_id && ["succeeded","failed"].includes(parsed.state) && Number.isSafeInteger(parsed.exit_code) && typeof parsed.timed_out === "boolean" && typeof parsed.cancelled === "boolean") {
        const latest=get("state");
        for (const [pending,item] of Object.entries(latest.outstanding)) if (item.host===args.host && item.job_id===args.job_id) {
          latest.settlements[pending]={...item,status:"authoritatively_ended",observed_state:parsed.state,exit_code:parsed.exit_code,terminal_receipt_sha256:record.native_receipt_sha256,observed_ms:Date.now()};
          delete latest.outstanding[pending];
        }
        setState(latest);
      }
      return {value:parsed,native_receipt_sha256:record.native_receipt_sha256,logical_tool_request_bytes:record.logical_tool_request_bytes,logical_tool_response_bytes:record.logical_tool_response_bytes,raw_store_key:prefix+key,pending_key:pendingKey};
    } catch (error) {
      record.finished_ms = Date.now(); record.elapsed_ms = record.finished_ms - record.started_ms;
      record.status = "failed"; record.failure = {name:error.name,message:error.message}; put(key,record); throw error;
    }
  }
  function originalArgs(request) {
    const r = checkedRequest(request);
    return {host:r.host,executable:PYTHON[r.host],args:["-u",WORKER_PATH[r.host],"--expected-request-sha256",r.request_sha256],cwd:WORKER_PATH[r.host].slice(0,WORKER_PATH[r.host].lastIndexOf("/")),env:clone(ENV),idempotency_key:r.idempotency_key,cpu_quota_percent:r.cpu_quota_percent,memory_max_bytes:r.memory_max_bytes,timeout_seconds:45,stdin:texts[r.request_id]};
  }
  function startResult(call,args) {
    const value = call.value, job = value.job;
    check(typeof value.reused === "boolean" && value.audit_recorded === true && job && typeof job.id === "string" && job.id && job.host === args.host && job.idempotency_key === args.idempotency_key && job.executable === args.executable && equal(job.args,args.args) && job.cwd === args.cwd && equal([...job.env_keys].sort(),Object.keys(args.env).sort()) && isSha(job.request_digest) && job.launch_state === "launched" && job.launch_error === null && value.launch && value.launch.ok === true, "native start receipt does not bind original request/launch");
    check(typeof job.request_fingerprint === "string" ? /^[0-9]+$/.test(job.request_fingerprint) : Number.isSafeInteger(job.request_fingerprint) && job.request_fingerprint >= 0, "exact decimal native fingerprint required");
    const current=get("state"), pending=current.outstanding[call.pending_key];
    check(pending && pending.host===args.host && pending.arguments_sha256===B.hashText(B.json(args)),"original pending launch identity lost");
    pending.job_id=job.id; pending.native_request_digest=job.request_digest; pending.status="acknowledged_awaiting_terminal"; setState(current);
    return {...call,job_id:job.id,start_arguments_sha256:B.hashText(B.json(args)),start_disposition:value.reused ? "reused" : "created",native_request_digest:job.request_digest,native_request_fingerprint:String(job.request_fingerprint)};
  }
  async function submit(request) {
    const r = checkedRequest(request), current = get("state");
    check(current.active === r.request_id.slice(0,4), "worker submit outside admitted graph");
    check(!get("original:"+r.request_id), "primary request already attempted; no fresh-ID retry");
    const args = originalArgs(r); put("original:"+r.request_id,{args_json:B.json(args),args_sha256:B.hashText(B.json(args)),attempted:true});
    const result = startResult(await native("process_start",args,"primary",r.request_id),args);
    put("original:"+r.request_id,{args_json:B.json(args),args_sha256:result.start_arguments_sha256,job_id:result.job_id,native_request_digest:result.native_request_digest,native_request_fingerprint:result.native_request_fingerprint,original_start:clone(result)});
    return result;
  }
  function terminal(value,jobId,maxStdout,maxStderr) {
    check(value.job_id === jobId, "native status changed job ID");
    check(["running","succeeded","failed"].includes(value.state), "unknown authoritative job state");
    if (value.state === "running" || value.output_complete !== true) return null;
    check(Number.isSafeInteger(value.exit_code) && typeof value.timed_out === "boolean" && typeof value.cancelled === "boolean", "complete terminal exit/timeout/cancel fields required");
    const sizes = {};
    for (const [stream,bound] of [["stdout",maxStdout],["stderr",maxStderr]]) {
      const count = value.log_bytes && value.log_bytes[stream];
      check(count && Number.isSafeInteger(count.seen) && count.seen >= 0 && count.seen <= bound && count.stored === count.seen && value.log_errors && value.log_errors[stream] === null && value.log_truncated && value.log_truncated[stream] === false, "complete bounded untruncated terminal logs required");
      sizes[stream] = count.stored;
    }
    check(value.state !== "succeeded" || (value.exit_code === 0 && !value.timed_out && !value.cancelled), "inconsistent successful native state");
    return {state:value.state,exit_code:value.exit_code,timed_out:value.timed_out,cancelled:value.cancelled,...sizes};
  }
  async function collectJob(request,submitted,instrument,lane,maxStdout=196608,maxStderr=8192) {
    let statusCall, end;
    const statusArgs = {host:request.host,job_id:submitted.job_id};
    for (let attempt = 0; attempt < 10; attempt++) {
      statusCall = await instrument("process_status",() => native("process_status",statusArgs,lane,request.request_id));
      end = terminal(statusCall.value,submitted.job_id,maxStdout,maxStderr);
      if (end) break;
      if (attempt < 9) await new Promise(resolve => setTimeout(resolve,3000));
    }
    check(Boolean(end), "authoritative terminal output unavailable within10 status observations");
    const parts = {stdout:[],stderr:[]}, offsets = {stdout:0,stderr:0}; let pages = 0;
    do {
      check(pages++ < 12, "bounded stdout pagination exceeded");
      const args = {...statusArgs,limit:16384,stdout_offset:offsets.stdout,stderr_offset:offsets.stderr};
      const call = await instrument("process_read",() => native("process_read",args,lane,request.request_id));
      check(call.value.job_id === submitted.job_id, "native read changed job ID");
      for (const stream of ["stdout","stderr"]) {
        const item = call.value[stream]; check(item && item.offset === offsets[stream] && item.size === end[stream] && typeof item.eof === "boolean", "read range/terminal size differs");
        const data = B.unhex(item.bytes_hex);
        check(data.length <= 16384 && item.next_offset === item.offset + data.length && item.next_offset <= item.size && item.eof === (item.next_offset === item.size) && (data.length > 0 || item.eof), "read cursor has holes/repeats/nonprogress or false EOF");
        parts[stream].push(data); offsets[stream] = item.next_offset;
      }
    } while (offsets.stdout !== end.stdout || offsets.stderr !== end.stderr);
    const finalCall = await instrument("process_status",() => native("process_status",statusArgs,lane,request.request_id));
    const final = terminal(finalCall.value,submitted.job_id,maxStdout,maxStderr);
    check(final && equal(final,end), "terminal status/log identity changed during collection");
    const out = parts.stdout.flat(), err = parts.stderr.flat();
    const record = {request_id:request.request_id,host:request.host,request_sha256:request.request_sha256,idempotency_key:request.idempotency_key,job_id:submitted.job_id,original_start_arguments_sha256:submitted.start_arguments_sha256,start_disposition:submitted.start_disposition,start_disposition_receipt_sha256:submitted.native_receipt_sha256,native_request_digest:submitted.native_request_digest,native_request_fingerprint:submitted.native_request_fingerprint,status:final.state === "succeeded" && final.exit_code === 0 ? "completed" : "failed",exit_code:final.exit_code,timed_out:final.timed_out,cancelled:final.cancelled,stdout_complete:true,truncated:false,stdout_bytes:out.length,stderr_bytes:err.length,stdout_base64:B.base64(out),stdout_sha256:B.sha256(out),stderr_base64:B.base64(err),stderr_sha256:B.sha256(err),authoritative_status_sha256:finalCall.native_receipt_sha256,initial_terminal_status_sha256:statusCall.native_receipt_sha256,read_pages:pages,native_process_cpu_ns:null,native_process_peak_rss_bytes:null,unexposed_native_process_cost_not_zero:true};
    put(`collected:${lane}:${request.request_id}`,record); return record;
  }
  async function collect(request,submitted,instrument) { checkedRequest(request); return collectJob(request,submitted,instrument,submitted.start_disposition === "reused" ? "recovery" : "primary"); }
  async function reconcile(request,jobId,instrument) {
    checkedRequest(request);
    const original = get("original:"+request.request_id); check(original && original.job_id === jobId, "cleanup must use original owned job");
    const call = await instrument("process_status",() => native("process_status",{host:request.host,job_id:jobId},"cleanup",request.request_id));
    check(call.value.job_id === jobId, "cleanup status changed job");
    return {status:"observed",observed_state:call.value.state,job_id:jobId,native_receipt_sha256:call.native_receipt_sha256,no_termination_called:true,termination_acknowledged:false,native_timeout_seconds:45,note:"Status-only reconciliation; original supervisor timeout remains active. process_cancel is not relabelled as terminate."};
  }
  async function helper(operation,envelope,keySuffix,{allowReused=false}={}) {
    const payload = B.json({schema:"hepta.fixed-cell-graph.native-wrapper.v1",operation,dispatch_sha256:dispatchSha,expected_wrapper_sha256:inputs.wrapper_sha256,...envelope})+"\n";
    check(size(payload) <= 1048576, "helper native stdin exceeds1MiB");
    const args = {host:"main",executable:PYTHON.main,args:["-u",WRAPPER],cwd:WORKTREE,env:clone(ENV),idempotency_key:`cell-graph-helper-${dispatchSha.slice(0,16)}-${keySuffix}-${B.hashText(payload).slice(0,16)}`,cpu_quota_percent:200,memory_max_bytes:2147483648,timeout_seconds:45,stdin:payload};
    const started = Date.now(), events = [];
    async function instrument(op,action) {
      check(events.length < 24 && Date.now()-started <= 60000, "bounded helper collection exceeded");
      const item = {operation:op,started_ms:Date.now(),status:"failed"}; events.push(item);
      try { const result = await action(); item.status="completed"; item.native_receipt_sha256=result.native_receipt_sha256; return result; }
      finally { item.finished_ms=Date.now(); if (item.finished_ms-started > 60000 || item.finished_ms<item.started_ms) throw new Error("helper completed call exceeded60s/clock bound"); }
    }
    const record = {operation,key_suffix:keySuffix,started_ms:started,status:"failed",events};
    try {
      const launchKey="helper-launch:"+args.idempotency_key, previous=get(launchKey);
      const start = startResult(await instrument("process_start",() => native("process_start",args,"helper:"+operation,keySuffix)),args);
      check(start.start_disposition === "created" || (allowReused && previous && previous.args_sha256===start.start_arguments_sha256 && previous.job_id===start.job_id && previous.native_request_digest===start.native_request_digest), "fresh reducer/helper unexpectedly reused or original publication identity unavailable");
      put(launchKey,{args_json:B.json(args),args_sha256:start.start_arguments_sha256,job_id:start.job_id,native_request_digest:start.native_request_digest});
      const collected = await collectJob({request_id:keySuffix,host:"main",request_sha256:B.hashText(payload),idempotency_key:args.idempotency_key},start,instrument,"helper:"+operation,196608,8192);
      record.collection=collected; check(collected.status === "completed", "native evidence helper failed; raw stdout/stderr retained");
      const result = B.parseJSON(B.text(B.unbase64(collected.stdout_base64)));
      check(result.schema === "hepta.fixed-cell-graph.native-wrapper-result.v1" && result.operation === operation && result.dispatch_sha256 === dispatchSha && result.wrapper_sha256 === inputs.wrapper_sha256, "wrapper output identity differs");
      record.status="completed"; record.result=result; return result;
    } finally { record.completed_ms=Date.now(); record.elapsed_ms=record.completed_ms-started; put("helper:"+operation+":"+keySuffix,record); }
  }
  function encoded(value) { const data=B.utf8(B.json(value)+"\n"); return {base64:B.base64(data),sha256:B.sha256(data)}; }
  async function reduce(collection,graph) {
    check(get("state").active === graph.graph_id && collection.graph_id === graph.graph_id && collection.dispatch_sha256 === dispatchSha, "reducer outside active graph");
    put("collection:"+graph.graph_id,clone(collection));
    const frozen=encoded(collection);
    const result = await helper("reduce",{graph_id:graph.graph_id,collection:frozen},graph.graph_id+"-reduce");
    check(result.graph_id === graph.graph_id && result.collection_sha256===frozen.sha256 && ["completed","failed"].includes(result.reduction.status) && isSha(result.reduction.receipt_sha256), "authoritative reducer result required");
    return {...result.reduction,native_wrapper:result.wrapper_cost};
  }
  async function publish(graph,collection,owner) {
    const current=get("state"); check(current.active===graph.graph_id && owner.graph_id===graph.graph_id && owner.dispatch_sha256===dispatchSha, "owner publication changed graph identity");
    put("collection:"+graph.graph_id,clone(collection)); put("owner:"+graph.graph_id,clone(owner));
    const frozenCollection=encoded(collection), frozenOwner=encoded(owner);
    const result=await helper("publish",{graph_id:graph.graph_id,collection:frozenCollection,owner:frozenOwner},graph.graph_id+"-publish",{allowReused:true});
    check(result.graph_id===graph.graph_id && result.collection_sha256===frozenCollection.sha256 && result.owner_sha256===frozenOwner.sha256, "published owner/collection byte identities differ");
    put("publication:"+graph.graph_id,result);
    const latest=get("state"); latest.next_graph++; latest.active=null; setState(latest);
  }
  async function replayOriginalStart(request,original) {
    const r=checkedRequest(request), current=get("state"), saved=get("original:"+r.request_id);
    check(current.next_graph===18 && current.active===null && Object.keys(current.outstanding).length===0 && current.recovery_active===r.request_id && saved && original.status==="completed" && original.exit_code===0 && original.stdout_complete===true && original.truncated===false && original.start_disposition==="created" && typeof original.stdout_base64==="string" && original.stdout_base64 && B.sha256(B.unbase64(original.stdout_base64))===original.stdout_sha256 && saved.job_id===original.job_id && saved.args_sha256===original.original_start_arguments_sha256 && saved.native_request_digest===original.native_request_digest, "successful original collection and complete census required for recovery");
    const args=B.parseJSON(saved.args_json); check(B.hashText(saved.args_json)===saved.args_sha256 && equal(args,originalArgs(r)), "stored original launch arguments changed");
    const result=startResult(await native("process_start",args,"recovery",r.request_id),args);
    check(result.start_disposition==="reused" && result.job_id===saved.job_id && result.native_request_digest===saved.native_request_digest && result.native_request_fingerprint===saved.native_request_fingerprint, "native idempotency lookup created/rebound original job"); return result;
  }
  async function publishRecovery(request,record) {
    checkedRequest(request); check(record.request_id===request.request_id && record.dispatch_sha256===dispatchSha, "recovery publication changed identity");
    put("recovery:"+request.request_id,clone(record));
    const frozen=encoded(record);
    const result=await helper("recovery",{request_id:request.request_id,record:frozen},request.request_id+"-recovery",{allowReused:true});
    check(result.request_id===request.request_id && result.record_sha256===frozen.sha256, "published recovery byte identity differs");
    const current=get("state"); current.recoveries.push(request.request_id); delete current.recovery_active; setState(current);
  }
  async function runNextGraph(graphId,executeOwner) {
    const current=get("state"), graph=dispatch.graphs[current.next_graph];
    check(current.active===null && Object.keys(current.outstanding).length===0 && graph && graph.graph_id===graphId && !current.recovery_active, "only next frozen graph with no outstanding original process may run; no retry/serial fallback");
    current.active=graphId; setState(current);
    return executeOwner(clone(graph),dispatchSha,adapter);
  }
  async function runRecovery(requestId,executeRecovery) {
    const current=get("state"), order=["b0-A-s0","b0-B-s0","b0-C-s0"];
    check(current.next_graph===18 && current.active===null && Object.keys(current.outstanding).length===0 && !current.recovery_active && order[current.recoveries.length]===requestId, "recovery only after settled complete primary census, in frozen order");
    const graphId=requestId.slice(0,4), collection=get("collection:"+graphId);
    const original=collection.workers.find(item=>item.request_id===requestId);
    current.recovery_active=requestId; setState(current);
    return executeRecovery(clone(requests[requestId]),clone(original),dispatchSha,adapter);
  }
  function snapshotRaw() {
    const current=get("state"), records=[];
    for(let i=0;i<current.raw_count;i++) { const item=get("raw:"+String(i).padStart(6,"0")); check(item,"raw receipt missing"); records.push(item); }
    const constructions=[];
    for(let i=0;i<current.construction_count;i++) constructions.push(get("construction:"+i));
    const value={schema:"hepta.fixed-cell-graph.native-ledger.v1",dispatch_sha256:dispatchSha,wrapper_sha256:inputs.wrapper_sha256,snapshot_ms:Date.now(),state:current,constructions,records,cost_scope:"Observed logical API JSON bytes, not wire/TLS bytes. Worker events are instrumented by frozen owner. Helper publication and this later ledger sealing are separate costs. This snapshot excludes its own future sealing calls; those remain in functions store."};
    const data=B.utf8(B.json(value)+"\n"); check(data.length<=268435456,"bounded raw ledger exceeded256MiB");
    const digest=B.sha256(data); put("ledger_snapshot:"+digest,B.base64(data)); return {data,sha256:digest,bytes:data.length,record_count:records.length};
  }
  async function flushRawLedger() {
    const snapshot=snapshotRaw(), total=Math.ceil(snapshot.bytes/524288), started=Date.now();
    for(let index=0;index<total;index++) {
      const chunk=snapshot.data.slice(index*524288,(index+1)*524288);
      const chunkSha=B.sha256(chunk);
      const chunkResult=await helper("raw_chunk",{ledger_sha256:snapshot.sha256,ledger_bytes:snapshot.bytes,total_chunks:total,index,chunk:{base64:B.base64(chunk),sha256:chunkSha}},`raw-${snapshot.sha256.slice(0,12)}-${index}`,{allowReused:true});
      check(chunkResult.index===index && chunkResult.chunk_sha256===chunkSha,"raw chunk acknowledgement changed exact bytes");
    }
    const result=await helper("raw_seal",{ledger_sha256:snapshot.sha256,ledger_bytes:snapshot.bytes,total_chunks:total},`raw-${snapshot.sha256.slice(0,12)}-seal`,{allowReused:true});
    check(result.ledger_sha256===snapshot.sha256 && result.ledger_bytes===snapshot.bytes,"sealed full native ledger identity differs");
    const receipt={...result,snapshot_record_count:snapshot.record_count,started_ms:started,completed_ms:Date.now(),snapshot_excludes_own_future_sealing_calls:true,all_sealing_raw_calls_retained_in_functions_store:true}; put("ledger_publication:"+snapshot.sha256,receipt); return receipt;
  }
  const adapter={submit,collect,reconcile,reduce,publish,replayOriginalStart,publishRecovery,runNextGraph,runRecovery,flushRawLedger,snapshotRaw,
    dispatch:clone(dispatch),dispatchSha256:dispatchSha,storePrefix:prefix,getState:()=>clone(get("state")),originalArguments:requestId=>clone(originalArgs(requests[requestId]))};
  const constructionState=get("state"), constructionIndex=constructionState.construction_count++;
  const constructionFinished=Date.now(); check(constructionFinished>=constructionStarted,"construction wall clock moved backwards");
  put("construction:"+constructionIndex,{started_ms:constructionStarted,completed_ms:constructionFinished,elapsed_ms:constructionFinished-constructionStarted,dispatch_bytes:size(inputs.dispatch_text),request_bytes_verified:Object.values(texts).reduce((n,v)=>n+size(v),0),scope:"Each adapter construction/reconstruction outside graph critical path; count every invocation as setup. Includes input verification/codec work, excludes script source evaluation, external transfer and final receipt publication; JS CPU/RSS unavailable."});
  setState(constructionState);
  return adapter;
}
