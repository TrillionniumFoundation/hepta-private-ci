# Durable learning cross-crate qualification slice

This extends the existing C1/ART/LRN qualification track, not the production host.
It composes the actual `DurableLedger` and artifact file APIs rather than an
in-memory substitute or separate Python implementation. No dependencies change.

The regression writes complete training decisions and independently named
observer outcomes to a file, closes/reopens against an acknowledgement anchor,
fits a bounded binary fixture policy ONLY from reopened eligible records, compares
it against a separate held-out oracle, persists baseline/candidate payloads and
registry history, and starts native executable processes for training and each
load/rollback generation. It no longer substitutes in-process byte vectors for
process generations.
It loads the predecessor through CURRENT registry eligibility to exercise rollback.
Then it persists revocation, rejects the old registry with the new witness,
rejects revoked candidate bytes, and rejects rollback after predecessor revocation.

The training/evaluation stage now opens an OS read-only file and calls the
shared-lock `inspect_ledger` port, not writable `DurableLedger::recover`.
The existing pure ledger rebuilds that exact validated snapshot before applying
revocations and fitting the fixture. File bytes and the original snapshot must
remain unchanged. Registry and payload reopens likewise use OS read-only files;
only initial writes and newly persisted revocations obtain writable handles.
The learner therefore receives neither a journal repair handle nor an artifact
writer during the read stage. This is a concrete read-port consumer, not a claim
of credential isolation or a continuously live writer/reader service.

The `tests/support/durable_process.rs` worker is an ignored libtest entrypoint
invoked explicitly by the parent with `--exact process::worker --ignored`.
`current_exe` resolves the actual test executable under Cargo and Bazel; every
worker is a fresh `exec`, with its PID checked against the spawned child and
against the parent. The parent waits for exit before starting the next generation.
Requests carry the separately retained registry witness and exact artifact ID,
generation, content, objective and compatibility tuple. Responses bind the actual
executable digest, request/configuration digest, process generation, loaded digest,
current registry head and observed ordering. They emit bounded
`HEPTA_C1_PROCESS_RECEIPT=` JSON records, always with `mode: reference`.

The frozen behavior probe contains the same two legal supported facts:
`title-order` produces `[supported-alpha, supported-beta]`; `freshness-order`
produces `[supported-beta, supported-alpha]`; rollback restores the first order.
This proves that selected immutable bytes change ordering after restart. Neither
policy gains source authority and this does not establish that one ordering is
better on real tasks. The held-out oracle and training outcomes remain synthetic.

Twelve worker executions cover training, missing acknowledged ledger history,
baseline/candidate/rollback generations, mismatched objective and compatibility,
corrupt payload, an old registry paired with the current witness, candidate
revocation, compatible rollback under that revocation, and predecessor revocation.
The parent also compares ledger and payload bytes before and after read stages.
The worker has no unanchored fallback or writer-recovery path. The ignored worker
is skipped as a standalone nextest test; it is exercised by the integration test.

Run with the repository test entrypoint:

    just test --locked -p codex-hepta-shadow-qualification --test durable_learning_roundtrip

The Bazel target is `//codex-rs/hepta-shadow-qualification:durable-learning-roundtrip`.
The dedicated CI runs exact source and actual-base synthetic merge independently,
plus ledger and artifact regressions. Compilation/execution remains pending until
those exact checks actually pass; no local success is inferred.

This is deterministic integration qualification, NOT longitudinal efficacy,
authenticated independent evaluation, the production C1 retrieval path, NDU
training, cross-fitted OPE or a production selection/rollback transaction. The
small fixture learner and oracle are deliberately labeled as such. Expected
recovery witnesses are retained in the test harness, not a production independent
witness service. Filesystem fixtures do not qualify physical power loss.

Remaining product attachment must provide authenticated observer/evaluator and
operator identities, preregistered evaluation using `learning.eval`, independently
durable current witnesses, normal host/port consumers, dataset-to-artifact
revocation orchestration, cross-store outbox reconciliation, target-host resource
measurements, real future windows and independently governed next-run selection.
A passed roundtrip would close only this integration sub-slice, never these gates.


## Dossier field coverage and remaining C1 stages

These are the eighteen integration-evidence fields for this bounded slice. A
missing product field remains missing; the fixture receipt is not an acceptance.

| Dossier field | Concrete binding or remaining dependency |
| --- | --- |
| Source receipt | Exact source-head and merge CI must bind this test invocation. |
| Guide digest | Candidate CI must bind `C1_EXECUTION.md`; no fabricated runtime guide receipt. |
| Source roots | `codex-rs/hepta-shadow-qualification/tests` plus native ledger/artifact owners. |
| Entrypoints | `durable_learning_roundtrip` and `process::worker`. |
| Consumer callsites | Native `inspect_ledger`, `read_registry_snapshot`, `read_candidate_payload`; test callers. |
| Host runtime identity | Worker PID and process generation; actual product host binding remains required. |
| Binary/artifact digest | SHA-256 executable, selected payload and registry witness in emitted receipts. |
| Configuration/body generation | Exact serialized worker-request digest and process generation; product body binding required. |
| Physical state | Temporary native ledger, immutable registry snapshots and payload files. |
| Schema/migration | Existing native codecs unchanged; no new migration profile. |
| Writer fence | Native cooperating file locks; no product writer authority claim. |
| Terminal observer | Parent fixture expected orders; authenticated independent observer still required. |
| Revocation source | Current parent-retained witness and actual native registry eligibility checks. |
| Fault results | Typed rejection receipts for lost acknowledged history, mixed tuples, corruption and revocation. |
| Resource measurements | Bounded request/streaming executable hash; no target-host latency/energy qualification. |
| Fallback | Reject load/inspection; no unanchored retry, silent policy replacement or mode upgrade. |
| Rollback predecessor | Baseline manifest and original ordering under current registry; revoked predecessor is denied. |
| External-gate disposition | All applicable independent acceptance, authority, efficacy and release gates remain external. |

Actual product callsites, context delivery observation, independent task outcomes,
authenticated dataset/evaluation/selection, and the fresh/expired/contradiction/
unauthorized/budget-overflow/revoke-at-delivery source probes remain
`integration_binding_required`. They cannot be inferred from this ranking probe.
Source/Memory/KG/tool mutation counters require those real owner and host ports;
byte equality here establishes only the tested native files' unchanged contents.
