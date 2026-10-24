/**
 * Existing process-owner adapter boundary. This file opens no port or host.
 * The root supplies frozen native start/status/read and local reducer bindings.
 * Actual tool payloads/results must be retained by the adapter, never fabricated.
 * A graph invocation stays within one owner script; no model turn between spans.
 */
async function executeCellGraph(graph, dispatchSha256, adapter) {
  const started = Date.now();
  let previousClock = started;
  const now = () => {
    const value = Date.now();
    if (value < previousClock) throw new Error("owner wall clock moved backwards");
    previousClock = value;
    return value;
  };
  const events = [];
  const cleanupEvents = [];
  async function call(operation, request, action) {
    const event = {operation, request_id: request.request_id, host: request.host,
      started_ms: now(), status: "failed"};
    events.push(event);
    try {
      const result = await action();
      event.status = "completed";
      event.native_receipt_sha256 = result.native_receipt_sha256;
      event.logical_tool_request_bytes = result.logical_tool_request_bytes ?? null;
      event.logical_tool_response_bytes = result.logical_tool_response_bytes ?? null;
      return result;
    } finally {
      event.finished_ms = now();
      event.elapsed_ms = event.finished_ms - event.started_ms;
    }
  }
  async function node(request) {
    const submittedAt = now();
    const record = {request_id: request.request_id, host: request.host,
      request_sha256: request.request_sha256, idempotency_key: request.idempotency_key,
      status: "failed", exit_code: null, stdout_complete: false, truncated: false,
      owner_node_started_ms: submittedAt};
    function checkDeadline() {
      const value = now();
      record.owner_collection_observed_ms = value;
      record.collection_elapsed_ms = value - submittedAt;
      if (record.collection_elapsed_ms > 60000) {
        record.collection_deadline_exceeded = true;
        throw new Error("observed collection exceeded60s; completed native events retained");
      }
    }
    try {
      // submit must preserve executable/argv/cwd/stdin/resources/idempotency key.
      const submitted = await call("process_start", request, () => adapter.submit(request));
      record.job_id = submitted.job_id;
      record.original_start_arguments_sha256 = submitted.start_arguments_sha256;
      record.start_disposition = submitted.start_disposition;
      record.start_disposition_receipt_sha256 = submitted.native_receipt_sha256;
      checkDeadline();
      if (submitted.start_disposition !== "created") throw new Error("primary cold worker was not authoritatively newly created");
      // collect uses this exact job ID. Each API call goes through instrument().
      const collected = await adapter.collect(request, submitted, async (operation, action) => {
        if (!["process_status", "process_read"].includes(operation)) {
          throw new Error("only bounded original status/read collection is authorized");
        }
        const count = events.filter(e => e.request_id === request.request_id).length;
        if (count >= 24 || now() - submittedAt > 60000) {
          throw new Error("bounded owner collection budget exceeded");
        }
        const result = await call(operation, request, action);
        record.last_completed_native_receipt_sha256 = result.native_receipt_sha256;
        checkDeadline();
        return result;
      });
      Object.assign(record, collected);
      checkDeadline();
      if (record.job_id !== submitted.job_id || record.start_disposition !== "created" || record.request_id !== request.request_id ||
          record.request_sha256 !== request.request_sha256 || record.idempotency_key !== request.idempotency_key) {
        throw new Error("collection changed the original job/request/effect identity");
      }
    } catch (error) {
      record.status = "failed";
      record.failure = {name: error.name, message: error.message};
      // The adapter must reconcile/terminate the exact outstanding job under the
      // existing process owner. Do not create a substitute or serial fallback.
      if (record.job_id && record.start_disposition === "created") {
        const cleanupStarted = now();
        const ownEvents = [];
        try {
          const result = await adapter.reconcile(request, record.job_id, async (operation, action) => {
            if (!["process_status", "process_terminate", "process_kill"].includes(operation) ||
                ownEvents.length >= 6 || now() - cleanupStarted > 30000) {
              throw new Error("separate bounded cleanup lane exceeded");
            }
            const event = {operation, request_id: request.request_id, host: request.host,
              job_id: record.job_id, started_ms: now(), status: "failed"};
            ownEvents.push(event); cleanupEvents.push(event);
            let value;
            try {
              value = await action();
              event.status = "completed";
              event.native_receipt_sha256 = value.native_receipt_sha256;
            } finally { event.finished_ms = now(); }
            if (now() - cleanupStarted > 30000) throw new Error("completed cleanup call exceeded30s; cost retained");
            return value;
          });
          record.cleanup = {result, status: "completed", started_ms: cleanupStarted,
            completed_ms: now(), events: ownEvents};
          if (record.cleanup.completed_ms - cleanupStarted > 30000) record.cleanup.status = "late";
        }
        catch (cleanupError) { record.cleanup = {status: "failed", message: cleanupError.message}; }
        record.cleanup.events = ownEvents;
        record.cleanup.started_ms = cleanupStarted;
        record.cleanup.completed_ms = now();
      }
    }
    return record;
  }
  // map invokes both submissions before awaiting either completion.
  const workers = await Promise.all(graph.requests.map(node));
  const collectedMs = now();
  const collection = {schema: "hepta.fixed-cell-graph.collection.v1",
    graph_id: graph.graph_id, dispatch_sha256: dispatchSha256, workers};
  const reducerStarted = now();
  let reduction;
  try { reduction = await adapter.reduce(collection, graph); }
  catch (error) { reduction = {status: "failed", failure: {name: error.name, message: error.message}}; }
  const completed = now();
  const firstCalls = events.filter(e => e.operation === "process_start");
  const overlaps = firstCalls.length === 1 ||
    Math.max(...firstCalls.map(e => e.started_ms)) <= Math.min(...firstCalls.map(e => e.finished_ms));
  const owner = {schema: "hepta.fixed-cell-graph.owner.v1", graph_id: graph.graph_id,
    dispatch_sha256: dispatchSha256, block: graph.block, arm: graph.arm,
    clock: "single owner Date.now UTC milliseconds; forward adjustment cannot be excluded",
    no_cross_host_clock_subtraction: true, started_ms: started, completed_ms: completed,
    critical_path_ms: completed - started, collect_path_ms: collectedMs - started,
    reducer_service_path_ms: completed - reducerStarted,
    concurrent_start_calls_observed: overlaps,
    requested_submission: graph.requests.length === 1 ? "one" : "Promise.all",
    events, cleanup_events: cleanupEvents, reduction, status: reduction.status, owner_record_publication_excluded: true,
    not_measured: ["service daemon CPU/RSS", "wire bytes including TLS/compression",
      "isolated physical network latency", "time before this owner script invocation"],
    no_serial_fallback: true};
  await adapter.publish(graph, collection, owner);
  return owner;
}

// After all18 primary graph records are sealed, replay ONLY b0-A-s0,b0-B-s0,b0-C-s0.
// The adapter calls native process_start with byte-identical original arguments
// and idempotency key, then reads the same authoritative completed job. Do not
// launch a new request if lookup fails. Retain extra API events/cost separately.

async function recoverCellGraphNode(request, original, dispatchSha256, adapter) {
  const started = Date.now();
  const events = [];
  const record = {schema: "hepta.fixed-cell-graph.recovery.v1", request_id: request.request_id,
    dispatch_sha256: dispatchSha256, started_ms: started, status: "failed",
    scope: "same-idempotency-key lookup/read after primary census; no injected crash"};
  async function call(operation, action) {
    if (!["process_start", "process_status", "process_read"].includes(operation)) throw new Error("recovery operation outside original lookup/read contract");
    if (events.length >= 24 || Date.now() - started > 60000) throw new Error("bounded recovery exceeded");
    const event = {operation, request_id: request.request_id, host: request.host,
      started_ms: Date.now(), status: "failed"};
    events.push(event);
    let result;
    try {
      result = await action();
      event.status = "completed";
      event.native_receipt_sha256 = result.native_receipt_sha256;
    } finally { event.finished_ms = Date.now(); }
    if (Date.now() - started > 60000 || event.finished_ms < event.started_ms) {
      throw new Error("completed recovery call exceeded clock/deadline bounds; event retained");
    }
    return result;
  }
  try {
    const submitted = await call("process_start", () => adapter.replayOriginalStart(request, original));
    if (submitted.start_disposition !== "reused" || submitted.job_id !== original.job_id ||
        submitted.start_arguments_sha256 !== original.original_start_arguments_sha256) {
      throw new Error("recovery created or rebound the original request/effect identity");
    }
    const collected = await adapter.collect(request, submitted, call);
    record.collection = {...collected, request_id: request.request_id, host: request.host,
      request_sha256: request.request_sha256, idempotency_key: request.idempotency_key,
      start_disposition: submitted.start_disposition, start_disposition_receipt_sha256: submitted.native_receipt_sha256,
      repeated_start_arguments_sha256: submitted.start_arguments_sha256};
    if (Date.now() - started > 60000) throw new Error("observed final recovery collection exceeded60s");
    if (collected.job_id !== original.job_id || collected.stdout_sha256 !== original.stdout_sha256 ||
        collected.stdout_base64 !== original.stdout_base64 || collected.status !== "completed") {
      throw new Error("authoritative cached output changed or is incomplete");
    }
    record.status = "completed";
  } catch (error) { record.failure = {name: error.name, message: error.message}; }
  record.completed_ms = Date.now();
  record.api_events = events;
  record.old_worker_cost_not_charged_again = true;
  await adapter.publishRecovery(request, record);
  return record;
}
