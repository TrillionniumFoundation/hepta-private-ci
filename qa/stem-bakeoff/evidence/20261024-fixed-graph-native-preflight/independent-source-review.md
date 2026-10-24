# Independent source review — graph native adapter

## Disposition

**Source review cleared for the corrected candidate below.** No additional
concrete API, identity, sequencing or evidence-loss blocker was found after the
three findings were addressed. This is permission to proceed to the original
owner's actual preflight/execution gates, not evidence that any real worker ran
or that distributed placement improved a result.

This review used local source, the supplied original Runtime schemas and the
already observed native start/status/read receipt examples. It did not contact a
host, read model/head/feature payloads or inspect scientific outcomes. The
original graph arithmetic, numerical tolerance, worker/owner code and study
budgets were not changed by this review.

## Exact reviewed candidate

| File | SHA-256 |
| --- | --- |
| `cell_graph_native_protocol.json` | `90e3aebfb50cb25809e18477fa99af4ecd4ac8557350114d2d5ad85b2eead972` |
| `cell_graph_native_helpers.js` | `a906c1516e7de1ef006a903b20ee4a0b12646d695b47449b0c593ed94dc870ca` |
| `cell_graph_native_adapter.js` | `df31a3a5a1fcedc8ff1b348e256f9a9a23176dc90dea873011361b8b4ed09f29` |
| `cell_graph_native_wrapper.py` | `fced1311223adde960d9e0c04fc40c8e816d01a4e078f09f802b67b20d3e5b45` |
| Original unchanged graph owner | `a8f1e561f3bff60b0247351c27619a874403006cd44ee40035b2cc3c8a1de112` |

The native protocol binds graph protocol
`2c88c2a47f56c05ea86f221ad26806fb5190bd17b8b32a9284a0ae31dfbe85e5`.
The earlier graph-protocol review history remains separate; its terminology-only
CPU-ceiling amendment is not a changed numerical experiment.

## Findings closed before execution

1. **A running or uncertain earlier launch could admit the next graph.** The
   first candidate reconciled a failed worker with one status observation and
   then advanced the graph pointer even if the original process was still
   running. An unacknowledged start could also have launched a real worker
   without leaving a known job ID. The corrected adapter records every worker,
   helper and recovery start as outstanding *before* the awaited original
   `process_start`. Only an authoritative terminal observation for the bound
   original host/job removes that outstanding record. Next-graph and recovery
   admission require no outstanding process. Unknown identities and running
   cleanup observations therefore block further dispatch. Failed evidence is
   still published; missing later graphs cannot become selected successes.
2. **An oversized reducer result could be lost before rejection.** The first
   wrapper checked captured stdout/stderr limits before retaining those bytes
   and the exit status. The corrected wrapper first retains bounded prefixes,
   exact observed lengths and hashes, truncation flags, and known exit status;
   then it rejects an over-limit result. Timeout observations are explicitly
   partial. The original 196,608 / 8,192 byte limits remain unchanged and no
   reducer retry was added.
3. **Session retention was described too strongly.** The corrected adapter and
   native protocol distinguish session-retained `functions.store` data from
   remote evidence publication. File fsync/hash checking is not represented as
   parent-directory or power-loss durability. Original Runtime job durability
   is a separate owner property. This study still injects no process crash or
   power failure.

## Source checks supporting the disposition

- Actual native `process_start`, `process_status` and `process_read` argument
  names match the supplied callable schemas. Hosts, interpreter paths, argv,
  cwd, environment keys, resources, full stdin and original idempotency keys
  derive from the frozen request inventory; no arbitrary caller path or code
  is added by the adapter.
- The adapter requires authoritative `created` primary starts and `reused`
  recovery starts. Exact arguments, host, job ID, request digest and fingerprint
  are checked. Unsafe JSON integer lexemes are retained as decimal strings in a
  separately parsed view; original MCP content text is stored before parsing.
  A rounded JavaScript number is not accepted as an exact large fingerprint.
- Collection uses the original job and independent byte cursors. It reads
  `bytes_hex`, checks offsets, sizes, progress, EOF and final terminal identity,
  and rejects truncation or incomplete results. Ten initial status observations,
  at most twelve bounded reads and one final status fit the existing 24-event
  budget including start. Owner pre/post-await deadline checks remain active.
- The actual cleanup is one instrumented status read. It neither invokes nor
  claims termination. Original 45-second supervisor timeouts remain in force;
  an unresolved job blocks the next graph instead of receiving a fabricated
  stop acknowledgement.
- Graph reduction runs the existing pinned reducer through a fixed wrapper,
  under the original owner. Helper costs are retained. The reducer helper is
  included in the enclosing graph critical path; later owner/raw publication
  is separately measured. Child CPU overlaps reducer accounting and must not
  be added twice. Native daemon cost and unavailable process counters stay
  unknown.
- Raw ledger snapshots are split into exact 512 KiB chunks, bounded by the
  original native stdin limit, hash verified, and assembled without overwrite.
  A snapshot explicitly excludes its own later publication calls; those calls
  remain in the session ledger with their separate costs.
- After-census recovery replays only the three fixed original starts and
  requires the same original job and complete exact output. It charges lookup/
  read/publication cost, not the old worker's CPU again. It is not crash
  recovery or general retry qualification.

## Verification observed

The corrected local logs report **18 JavaScript constructed transport checks**
and **11 Python wrapper checks**, all passed. The review independently checked
the actual source hashes above and read the new uncertainty/terminal-status and
oversized-output regressions. Those checks exercise codecs, bindings, pagination,
evidence retention and failure gates using constructed fixtures; they are not
real native graph executions or performance measurements. No redundant local
rerun or remote job was started by the reviewer.

## Remaining actual-run gates and claim limits

Root must still bind the executed adapter/wrapper/worker source, current native
tool contracts, original dispatch, real environment receipts and per-worker
own-cgroup limits. Those physical values must come from the actual run. Passing
the local fixtures cannot populate them. Every failed, uncertain or unrun
expected graph stays visible in the complete eighteen-graph census; paired
cost conclusions remain blocked unless the registered complete-case gate passes.

Equal sums of configured CPU ceilings are not reserved capacity or equal CPU
work. Different host stacks remain part of the operational treatment. Logical
JSON payload bytes are not wire/TLS bytes; per-process RSS peaks are not unique
whole-system memory. This experiment tests fixed six-head inference placement
and cold dispatch, not learning, cell division, a native agent loop or emergent
general intelligence.
