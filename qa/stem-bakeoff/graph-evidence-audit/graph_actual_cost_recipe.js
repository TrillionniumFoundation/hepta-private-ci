/* Optional root-side evidence capture only. Evaluate in the same functions V8
 * as the already frozen adapter/owner. No automatic execution or host calls.
 * The frozen owner and its measured intervals are not modified.
 */
const GraphActualEvidence = (() => {
  async function capture(adapter, kind, id, action) {
    const prefix = adapter.storePrefix;
    const ownerKey = kind === "graph" ? "owner:" + id : "recovery:" + id;
    const receiptKey = prefix + "outer:" + kind + ":" + id;
    if (load(receiptKey) !== undefined) throw new Error("outer cost attempt already recorded; refusing repeat without overwriting evidence");
    const before = Date.now();
    store(receiptKey, {kind, id, capture_status:"pending", call_started_ms:before,
      returned_or_threw_ms:null, total_call_elapsed_ms:null, original_owner_source:"not_yet_observed",
      scope:"Original outer attempt persisted before await; unknown completion/cost is not zero. No automatic repeat."});
    let result = null, caught = null, returned = false;
    try {
      result = await action();
      returned = true;
    } catch (error) {
      caught = error;
    } finally {
      const after = Date.now();
      // publish/publishRecovery can reject after the real owner was constructed.
      const retained = load(prefix + ownerKey);
      const actual = result || retained || null;
      const identity = actual && (kind === "graph" ? actual.graph_id : actual.request_id);
      const hasTimes = identity === id && Number.isInteger(actual.started_ms) && Number.isInteger(actual.completed_ms);
      store(receiptKey, {
        kind, id, capture_status: caught ? "threw" : "returned", call_started_ms: before, returned_or_threw_ms: after,
        total_call_elapsed_ms: after - before, returned,
        original_owner_source: result ? "returned" : retained ? "session_store_after_unreturned_owner" : "unavailable",
        original_owner_started_ms: hasTimes ? actual.started_ms : null,
        original_owner_completed_ms: hasTimes ? actual.completed_ms : null,
        original_owner_status: actual ? actual.status : null,
        before_original_owner_ms: hasTimes ? actual.started_ms - before : null,
        after_original_owner_ms: hasTimes ? after - actual.completed_ms : null,
        original_graph_critical_path_ms: kind === "graph" && actual ? actual.critical_path_ms ?? null : null,
        original_recovery_elapsed_ms: kind === "recovery" && hasTimes ? actual.completed_ms - actual.started_ms : null,
        wall_clock_order_valid: after >= before && (!hasTimes || before <= actual.started_ms && actual.started_ms <= actual.completed_ms && actual.completed_ms <= after),
        failure: caught ? {name: caught.name, message: caught.message} : null,
        scope: "Same functions Date.now clock. Original owner timestamps stay unchanged. The after-owner interval covers publication/return or its failure; all intervals are nested subsets of total_call_elapsed_ms, never added twice. Null means unavailable, not zero."
      });
    }
    if (caught) throw caught; // Preserve stop/no-next-graph behavior.
    return result;
  }
  async function graph(adapter, graphId, executeOwner) {
    return capture(adapter, "graph", graphId, () => adapter.runNextGraph(graphId, executeOwner));
  }
  async function recovery(adapter, requestId, executeRecovery) {
    return capture(adapter, "recovery", requestId, () => adapter.runRecovery(requestId, executeRecovery));
  }
  async function flush(adapter) {
    const receiptKey=adapter.storePrefix + "outer:ledger";
    if (load(receiptKey) !== undefined) throw new Error("ledger flush outer attempt already recorded; refusing repeat without overwriting evidence");
    const before = Date.now(), rawBefore = adapter.getState().raw_count;
    store(receiptKey, {capture_status:"pending", call_started_ms:before, returned_or_threw_ms:null,
      total_call_elapsed_ms:null, raw_count_before_snapshot:rawBefore,
      scope:"Original flush attempt persisted before await; unknown completion/cost is not zero. No automatic repeat."});
    let result = null, caught = null;
    try { result = await adapter.flushRawLedger(); }
    catch (error) { caught = error; }
    finally {
      const after = Date.now();
      store(receiptKey, {
        capture_status:caught ? "threw" : "returned", call_started_ms: before, returned_or_threw_ms: after, total_call_elapsed_ms: after - before,
        wall_clock_order_valid: after >= before, raw_count_before_snapshot: rawBefore,
        returned_publication_receipt: result,
        failure: caught ? {name: caught.name, message: caught.message} : null,
        scope: "Includes snapshot serialization/hash and subsequent raw chunk/seal path. Separate post-study publication cost; not added to graph or recovery wall. The returned adapter receipt begins after snapshot construction."
      });
    }
    if (caught) throw caught;
    return result;
  }
  function exportAfterSealing(adapter, firstUnsealedNativeIndex) {
    const prefix = adapter.storePrefix, state = adapter.getState();
    if (!Number.isInteger(firstUnsealedNativeIndex) || firstUnsealedNativeIndex < 0 || firstUnsealedNativeIndex > state.raw_count) {
      throw new Error("exact original ledger snapshot record count required");
    }
    const helperKeys = new Set(), rawTail = [], missing = [];
    for (let i = 0; i < state.raw_count; i++) {
      const record = load(prefix + "raw:" + String(i).padStart(6,"0"));
      if (!record) { missing.push(i); continue; }
      if (record.lane.startsWith("helper:")) helperKeys.add(record.lane + ":" + record.request_id);
      if (i >= firstUnsealedNativeIndex) rawTail.push(record);
    }
    const constructions = [];
    for (let i = 0; i < state.construction_count; i++) constructions.push(load(prefix + "construction:" + i) ?? null);
    const costs = {
      source: "Exact session-retained adapter/helper objects plus outside-owner same-clock receipts; no values imputed",
      dispatch_sha256: adapter.dispatchSha256, state,
      helpers: [...helperKeys].sort().map(key => ({store_key: prefix + key, record: load(prefix + key) ?? null})),
      graph_outer_spans: adapter.dispatch.graphs.map(item => ({graph_id: item.graph_id, record: load(prefix + "outer:graph:" + item.graph_id) ?? null})),
      recovery_outer_spans: ["b0-A-s0","b0-B-s0","b0-C-s0"].map(id => ({request_id: id, record: load(prefix + "outer:recovery:" + id) ?? null})),
      ledger_outer_span: load(prefix + "outer:ledger") ?? null,
      session_retained_unpublished: adapter.dispatch.graphs
        .filter(item => !load(prefix + "publication:" + item.graph_id))
        .map(item => ({graph_id: item.graph_id,
          owner: load(prefix + "owner:" + item.graph_id) ?? null,
          collection: load(prefix + "collection:" + item.graph_id) ?? null,
          scope: "Unpublished or unattempted original session object; preserve separately, do not substitute it for a successful native publication."})),
      session_retained_unpublished_recovery: ["b0-A-s0","b0-B-s0","b0-C-s0"]
        .filter(id => !state.recoveries.includes(id))
        .map(id => ({request_id: id, record: load(prefix + "recovery:" + id) ?? null})),
      missing_raw_indices: missing
    };
    const tailLedger = {
      schema: "hepta.fixed-cell-graph.native-ledger.v1", dispatch_sha256: adapter.dispatchSha256,
      wrapper_sha256: state.wrapper_sha256, snapshot_ms: Date.now(), state,
      constructions, records: rawTail, partial_tail_export: true,
      first_native_index: firstUnsealedNativeIndex, missing_raw_indices: missing,
      scope: "Exact raw calls after the original sealed ledger's snapshot. Combine by native index; do not count overlapping records twice. This session export makes no power-loss durability claim."
    };
    store(prefix + "postrun:helper-costs", costs);
    store(prefix + "postrun:raw-tail", tailLedger);
    return {costs, tailLedger};
  }
  return {graph, recovery, flush, exportAfterSealing};
})();
GraphActualEvidence;
