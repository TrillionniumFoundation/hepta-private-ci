# inference.worker hardening status and recovery runbook

Date: 2026-09-28. Work branch: `codex/inference-worker-hardening-20260928`.
Initial source: `a126987b84737dbc2ee2592442a314117bddb4a2`.

This document describes the changes in PR #1143. It is not a passing native
qualification receipt, production activation, independent acceptance, or release.
The seven-stage remediation is **partially implemented**, not closed. In
particular, the local verified-authority/async driver and durable execution
integration remain repository implementation work, not merely external evidence.

## 1. Profile and compatibility boundary

| Profile | Current scope | Build selection |
| --- | --- | --- |
| HostedAppServerWorker | Production candidate; existing final-use authority and durable inference.control owner remain mandatory | Default library and `--profile native-app-server` CLI |
| LocalModelWorker | Experimental, synchronous injected-driver component; not production local inference | Explicit non-default `experimental-local-worker` Cargo feature |
| LegacyReceiptBoundary | Validation-only v1 receipts; supplied observations are not provider/device attestations | Default library |

`src/profiles.rs` reports classification, not authority. Enabling the experimental
feature cannot promote its maturity. The CLI does not add a local-model profile.
The legacy v1 wire meaning and digest construction are preserved: its numeric
`consumed_tokens` cannot distinguish absent observation from observed zero and
must not be used as trusted billing evidence. The hosted path retains optional
usage; `None` remains unknown.

The experimental `ModelDriver` now needs an explicit `load_with_budget`
implementation. Its default returns `UnboundedDriver`, not a fallback call to
unbounded `load`. This is an intentional opt-in break for injected drivers. It
does not attest that a driver obeyed its allowance. Its `inspect_model` default
is `Unknown`; a physical release cannot be inferred from a missing local handle.

## 2. Experimental resource and operation state

The worker passes the **remaining aggregate** resident-memory allowance to each
synchronous load. Exhausted capacity is rejected before driver entry. All known
loaded handles contribute to checked aggregate accounting. Neuron feature
observations also include transient allocation bytes in the aggregate check.
This is reported-memory accounting and a bounded driver contract, not an OS/GPU
memory controller, a reservation ledger shared between processes, or a complete
RAII ResourceManager.

Acquired handles are recorded before handle validation or fallible cleanup.
The following transitions preserve ownership:

| Condition | Action | Ownership afterwards |
| --- | --- | --- |
| Successful bounded load and valid observation | Admit model as Ready | Exact handle remains in the model table |
| Invalid handle or over-budget load | Attempt physical unload after recording handle | Remove only after unload succeeds |
| Unload error or lost acknowledgement | Mark RepairRequired | Original handle and reported memory remain owned |
| Repair inspection is Unknown | Refuse release/retry | Continue holding handle and capacity |
| Repair inspection proves Present | Retry unload of the exact handle | Remove only on observed release success |
| Repair inspection proves Absent | Remove exact handle | Do not send another unload |
| Nonterminal execution or driver error | Hold active slot, mark repair, fence instance | No new execution and no ordinary unload of an active model |
| Explicit device-generation fence | Refuse new load/run | Safe cleanup of idle Ready models remains available |

Grant expiry or revocation does not prevent safe cleanup. Arithmetic is checked;
underflow and overflow are errors rather than saturating changes to ownership.
A driver error during load cannot prove that no resource was acquired; the
instance is conservatively fenced. The old error type still cannot return a
reconcilable handle for every partial-load failure. A real driver must retain
such ownership internally until the typed partial-acquisition protocol exists.

The request history is bounded at 16,384 entries **inside this worker instance**.
It binds request kind, model name, complete loaded manifest and original request.
Identical post-entry requests return cached observations without driver re-entry;
changed semantics conflict. A driver error leaves an unknown entry and its active
slot. A nonterminal result remains indeterminate and cannot refund capacity.
History is not silently evicted to admit another operation.

This history is not persisted. It does not establish crash durability, prevent
replay after constructing another worker, or replace inference.control. Do not
restart the process, change the request ID, or clear its history as a way to
resolve an uncertain model effect. Pre-entry cancellation and true durable local
terminal records still need the shared control-owner integration.

## 3. Hosted reconcile-only entrypoint

`AppServerModelDriver::reconcile_only` and CLI `--reconcile-only` inspect an
**existing** durable operation. They never reserve a new operation or issue
`turn/start`. A successful exact-history reconciliation may update the existing
inference.control journal; this is not a filesystem read-only operation.

The caller must supply the original prompt bytes, optional context query, Agent
identity/generation, model, Agentd socket, timeout and optional intelligence
binding. These identify a historical fact; they do not reauthorize execution.
Identity drift is rejected before returning cached output or querying history.
An unknown request ID is rejected rather than being created. A Reserved,
pre-dispatch-stopped or explicitly rejected record is not dispatched or released
by this interface.

For a dispatched operation, only the existing authenticated App Server history
adapter may supply a terminal observation. The interface deliberately has no
parameter that lets an operator submit an arbitrary `terminal=true` value. If
exact evidence is unavailable, the stored observation or `None` is returned and
the reservation remains as it was. Cached terminal output is returned unchanged,
including unknown usage.

Example (all values are the original operation's values):

```sh
hepta-infer-worker --profile native-app-server --reconcile-only \
  --agentd-socket "$AGENTD_SOCKET" --agent-id "$AGENT_ID" \
  --generation "$ORIGINAL_GENERATION" --model "$ORIGINAL_MODEL" \
  --journal "$JOURNAL" --request-id "$ORIGINAL_REQUEST_ID" \
  --maximum-in-flight "$ORIGINAL_MAXIMUM_IN_FLIGHT" \
  --timeout-ms "$ORIGINAL_TIMEOUT_MS" \
  --final-use-authority-config "$AUTHORITY_CONFIG" < "$ORIGINAL_PROMPT_FILE"
```

Supply the original `--context-query` and all four `--intelligence-*` fields when
present. Preserve prompt newlines exactly. The CLI still validates its protected
authority configuration; reconciliation does not request a new model-effect grant.
A nonterminal, absent or unsuccessfully authorized terminal result exits with an
error, rather than being advertised as successful inference.

### Incident handling

Retain the original journal and authority state under their existing owner. Record
the operation identity, current state, original source admission and dispatch
correlation without logging prompts, secrets or private signing material. Use
reconcile-only with the original inputs. If no exact evidence is available,
retain the uncertain reservation and escalate to the control/provider owner.
Do not delete the journal, mint a replacement request, shorten a TTL, infer zero
usage, or mark an operation not-sent on the basis of elapsed time or process loss.

The App Server currently uses ephemeral threads. History can disappear after
process loss; this command cannot manufacture a terminal fact. A persistent
history/retention contract, independently authenticated late usage observations,
and durable quarantine/adjudication still need implementation and qualification.
The existing two-second turn-start reconciliation grace is unchanged in this
patch; bounded configurable grace and delay-injection tests remain open.

## 4. Native qualification and evidence

The new `.github/workflows/hepta-inference-worker-qualified.yml` supplements the
existing shared workflows. It does not erase their failures. It selects exact
source-head and a fixed-base synthetic merge on Ubuntu and macOS. Separate owner
steps run inference.control, inference.worker and Agentd; one owner's failure
does not suppress later owner execution when prerequisites succeeded.

Each owner gets separate formatting, library, binary-target, all-target check and
strict Clippy commands. Worker commands run both default and experimental builds.
The runner retains bounded command logs, freshly generated JUnit and a generated
`CURRENT_STATUS.json` outside the tracked checkout. A missing, stale, malformed,
empty, failing or skipped JUnit report cannot produce a passing library result.
Retries are disabled. `cargo test --bins` proves only the binary targets it
actually exercises; it is not a real product-process or provider qualification.

The status artifact binds source head/tree, tested head/tree, fixed base, Git blob
identities, package, OS, lane and Actions run/attempt. Blob identities describe the
**tested tree**, including the synthetic merge when applicable. Other OS/lane
results are not inferred from one artifact. Require all expected matching
artifacts and successful workflow conclusions before claiming the matrix passed.
Tracked HEAD, worktree and index must remain unchanged; the current runner does
not provide a complete attestation of untracked files or external dependencies.
Real hardware, real provider, product composition and independent acceptance are
separate `not_executed` fields. Activation and release remain false.

The historical `IMPLEMENTATION_MAP.json.sourceBase` is provenance and is not
rewritten to pretend these tests ran on a newer candidate. `existing_bound`,
documentation closure, a command string or an operation map is never current
passing qualification. The generated main guide, map/dossier projections and
source registry still need their canonical regeneration and successful validation;
this document does not certify their closure.

### Verification recorded in this work session

The two Python qualification-runner files were actually tested locally:

```sh
python -W error::ResourceWarning -m unittest discover \
  -s scripts -p 'test_hepta_inference_worker_qualification.py' -v
```

Eight tests passed. `LOCAL_VALIDATION_2026_09_28.json` records their exact Git blob
identities and log digest. The tests exercise real subprocess failure/timeout,
Git candidate binding, JUnit validation, stale-report rejection and atomic status
writing. The stale-report test mocks the native command runner; its success is
**not** Rust or provider evidence.

Seventeen new Rust source tests are included: twelve experimental resource/fault
cases, four reconcile-only cases, and one profile classification case. They were
not executed in the editing environment, which has no Rust toolchain. No native
compilation, Rust tests, rustfmt, Clippy, macOS or hardware pass is claimed. Actual
Actions conclusions must be read for the final commit, not an earlier revision.

## 5. Seven-stage closure ledger

| Stage | Implemented in this patch | Still required |
| --- | --- | --- |
| A: credible baseline | Per-owner source/merge/OS workflow and exact command/JUnit recording | Diagnose and fix original grouped-library/projection failures; obtain passing current native results on both OSes |
| B: profile boundary | Non-default experimental feature, explicit maturity, legacy validation-only documentation | Native feature-matrix verification and product caller qualification |
| C: verified local authority/async driver | No production claim is made by the old injected driver | Sealed verified grants/manifests/attested handles, trusted clock, signature/nonce/revocation/subject bindings, real input bytes, async load/run/inspect/unload and live cancellation/deadlines |
| D: resource ownership | Aggregate reported memory, bounded-load opt-in, failed-release handle retention, repair inspection, checked arithmetic and generation fence | Shared atomic RAII ResourceManager, reliable partial-acquisition handles, actual device/OS measurements, weights/KV/transient enforcement and process-crash cleanup |
| E: durable local no-replay | Bounded exact in-instance history and uncertain-slot retention | Integrate existing inference.control durable owner, dispatch witness/handle identity, crash reconciliation and terminal/usage records; no separate competing journal |
| F: hosted reconciliation | Reconcile-only API/CLI and exact identity checks, without new inference or fabricated usage | Missing-history adjudication, trusted late usage reconciliation, bounded configurable grace, operational metrics and provider retention contract |
| G: documentation/evidence | This concrete runbook, exact-blob local Python record and generated per-run status artifacts | Canonical guide/map/dossier regeneration, registry checks and complete final-candidate evidence aggregation |

These remaining rows are engineering work. External target-host qualification,
issuer/key custody, trusted time, revocation distribution, canary, rollback and
independent acceptance are additional gates, not substitutes for that work.
