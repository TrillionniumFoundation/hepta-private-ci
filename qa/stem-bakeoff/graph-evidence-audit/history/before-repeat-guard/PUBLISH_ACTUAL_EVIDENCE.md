# Actual fixed-graph evidence: bounded publication and audit plan

This plan adds no experimental arm, threshold, test, training or native service.
It packages the actual frozen18-graph/30-worker/3-recovery census, including
missing and failed entries, and reruns only the original read-only reporter.
Do not fill any result before the original owner has produced it.

## Capture the post-owner costs with the same functions clock

The frozen `executeCellGraph` returns `owner.started_ms`, `owner.completed_ms`,
`critical_path_ms`, `collect_path_ms`, and `reducer_service_path_ms`.
`recoverCellGraphNode` returns `record.started_ms` and `record.completed_ms`;
it does not have `critical_path_ms`. Both end timestamps precede publication.

The separate `graph_actual_cost_recipe.js` contains definitions only. Its
`graph` and `recovery` wrappers capture the same functions clock immediately
before/after awaiting the existing adapter calls. They do not change the owner.
If publication throws, they read the exact already-retained `owner:<graph_id>`
or `recovery:<request_id>` object. If that object does not exist, timestamps
remain null. The error is rethrown, preserving the original stop/admission gate.

```javascript
const actualEvidence = eval(load("hepta.graph.actual-cost-recipe.source"));
const result = await actualEvidence.graph(adapter, graph.graph_id, module.execute);
// After the full primary census, in the frozen order:
const replay = await actualEvidence.recovery(adapter, requestId, module.recover);
```

The post-owner interval is `returned_or_threw_ms - original_owner_completed_ms`.
It includes publication encoding, helper/API work and return/failure handling.
The helper's own recorded wall is a subset: envelope preparation precedes its
timer. Do not add the post-owner interval, helper wall and API spans together.

After all permitted primary/recovery work, capture the complete ledger flush:

```javascript
const sealed = await actualEvidence.flush(adapter);
const exported = actualEvidence.exportAfterSealing(
  adapter, sealed.snapshot_record_count
);
```

The outer flush clock includes snapshot encoding/hash work that precedes the
adapter's own returned publication timer. If flush throws, the outer failure
receipt and exact raw indices remain in session store. A failed owner or flush
must not be silently rerun. Missing later rows remain missing.

`exported.costs` is the exact helper/outer-span export for `helper-costs.json`.
`exported.tailLedger` is the exact later-call export for `raw-sealing-tail.json`.
Do not print these large objects to chat. Publish them as bounded file bytes,
record their SHA256 and the extra export/publication cost. This export performs
no host calls; its later transfer is external publication overhead.

The export also retains original session owner/collection/recovery objects that
were not successfully published, including nulls for unattempted cases. Keep
these under the separate session-export evidence boundary. Do not substitute
them into the successful native publication paths or promote them to completed
pipeline cases. They retain known failed-owner costs when publication threw.

The raw tail is necessary because the first sealed ledger cannot contain its
future own-sealing API calls. Merge raw call records by their original index;
overlapping records must be identical. The auditor accepts repeated `--ledger`
arguments and rejects conflicting duplicates or index holes. A tail's
`constructions` array is the complete original indexed array, not a renumbered
suffix. No new measurements or missing native responses are fabricated.

## Preserve one complete evidence tree

Preserve the frozen graph protocol, native adapter protocol, tested source
hashes, exact environment/physical-host evidence, exact six-head graph export,
the prepared dispatch and all30 original request JSON files. These already
exist; do not regenerate the export or choose a different original head.

Preserve the whole task-owned main graph evidence tree, including:

- Every existing `graphs/<graph_id>/collection.json`, `owner.json`, reducer
  launch intent, CLI stdout/stderr/exit/output metadata, timeout metadata,
  reduction receipt and prediction archive. Never replace failed directories.
- Every existing `graphs/recovery/b0-{A,B,C}-s0.json`; absent records stay absent.
- Full raw ledger chunks/manifests/assembled files and wrapper receipts,
  including partial or failed publication. Keep the raw sealing tail separately.
- Exact helper and outside-owner cost exports, session stop/outstanding state,
  source/install/gate logs, and setup/transfer receipts.

No source-corpus labels, original encoder weights or unrelated machine files
are needed. The graph output archives contain inference probabilities only;
they are sufficient for the unchanged reporter's parity check.

Create a SHA256/byte-count manifest of all packaged regular files. Keep the
manifest, archive hash/size and transfer receipt with the eventual evidence PR.
If archive transport requires parts, use deterministic byte ranges and preserve
both per-part and full archive hashes. A final publication acknowledgement
cannot be inside the archive it acknowledges; retain its original receipt as
an adjacent publication record. Do not call that boundary a power-loss test.

## Retain costs without constructing an unsupported total

Keep the original receipts for code deployment, environment inventories, graph
export, request preparation, adapter installation/gates, and input transfer.
The observed30-request transfer receipt is a setup cost, not graph inference
latency. Retain its actual source record rather than copying a chat number.

`setup-costs.json` can be a small index of those actual measurements:

```json
{
  "entries": [
    {
      "phase": "actual phase name",
      "metrics": {},
      "scope": "what the original receipt actually measured",
      "receipts": [{"file": "relative/task-owned/receipt.json", "sha256": "actual SHA256"}]
    }
  ],
  "unmeasured": ["actual missing cost components"]
}
```

This is a publication index, not a new experiment protocol. Values are filled
from actual receipts only. `metrics` names can match the original receipt.
Root's heterogeneous setup metrics are source-hash-linked; the auditor does
not invent or reinterpret them as a single comparable timer.

Report the original owner graph wall, worker/reducer CPU and RSS separately.
Worker/reducer phases and reducer helper wall are nested inside graph wall.
Concurrent API/node walls are not summed as graph latency. Wrapper child CPU
overlaps original reducer CPU. Process RSS peaks are not simultaneous or unique
host-wide physical memory. Reused recovery returns old output and does not
recharge its old worker CPU. Record every adapter construction and all observed
post-owner publication, flush and final transfer costs separately.

Service-daemon and external JavaScript-owner CPU/RSS, wire/TLS bytes, effective
ancestor limits and host contention remain unmeasured. Missing quantities stay
unknown. Do not infer whole-system net benefit from the measured subset.

## Run the unchanged reporter and the independent integrity audit

The new audit uses the original pinned `cell_graph_report.py`,
`cell_graph_reduce.py` and `cell_graph_worker.py` without changing their bytes.
It invokes the reporter in a fresh subprocess and writes to a new directory.
It independently checks the complete census, raw paired differences, native
start identities, raw page reassembly and cost/provenance links.

```bash
/data/hepta-cell-input-20261024/.venv/bin/python audit_cell_graph_evidence.py \
  --source-dir /home/qian-qi/workspace/hepta-cell-graph-benchmark-20261024/qa/stem-bakeoff \
  --dispatch /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/requests-v1/dispatch.json \
  --evidence-root /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024 \
  --environment-receipt ACTUAL_FROZEN_ENVIRONMENT_FILE \
  --ledger ACTUAL_ASSEMBLED_RAW_LEDGER_FILE \
  --ledger ACTUAL_RAW_SEALING_TAIL_FILE \
  --helper-costs ACTUAL_HELPER_COSTS_FILE \
  --setup-costs ACTUAL_SETUP_COST_INDEX_FILE \
  --published-report ACTUAL_ORIGINAL_REPORT_FILE \
  --output NEW_AUDIT_DIRECTORY
```

If no reporter output has yet been published, omit `--published-report`; the
audit generates `recomputed-report.json` using the original reporter. If a cost
document is unavailable, omit its flag and the audit marks it missing, never
zero. A missing/failed experimental row is a valid negative outcome. It must
block complete-census comparisons and remain visible even if other rows pass.
The audit separately retains known failed-owner costs when the original
reporter's failure row has insufficient data to include them.

Audit exit zero means no detected evidence integrity inconsistency. It does
not mean all experimental conditions passed. Read both
`original_reporter_completed_comparable_graphs` and
`qualified_primary_cost_comparison`; recovery qualification remains separate.
For missing cases, original and rerun failure text can name different local
paths. Both complete reports remain preserved; failure strings are not silently
normalized. Structured status/cost/parity summaries must agree. A complete
successful report must agree byte for byte.

## Published interpretation

Use all18 predeclared graph records and all six within-block differences.
Primary is C−B; C−A and B−A are secondary. Only the original full-census gate
authorizes the descriptive paired summary. No selected successful subset, new
reference, widened tolerance, confidence interval or population-tail claim.

The result concerns the same fixed graph on the actual heterogeneous main and
pocket4 stacks, including their different Python/NumPy/hardware/service paths.
It does not isolate physical network latency or CPU architecture. The six
unchanged original warmup heads and fixed features provide no evidence by
themselves of new task learning, beneficial split/edges, migration learning,
native-agent competence, or AGI.
