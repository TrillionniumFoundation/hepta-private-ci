# V9: continual parameter memory, bounded adaptation, and transferred state

This research candidate extends the existing Hepta memory owner, typed read
contracts, parameter runtime, learning-artifact publication, and TaskFlow
lifecycle. It is an executable qualification of those mechanisms. It does not
establish an autonomous general memory system, a compression advantage, or a
positive full-cost return from changing topology.

## Six delivery surfaces

| Goal | Implementation | Evidence and acceptance boundary |
| --- | --- | --- |
| Typed semantic addressing | Existing `MemoryRequestV1` / `MemoryReadoutV1`; V9 operation/reject head and operation-conditioned compatibility heads; a pinned native worker profile and exact retained worker responses | Public selection, independent calibration, independent held language, and the same held native requests through frozen V7/V8/V9 arms. Language-quality failure remains separate from successful execution. |
| Event, semantic, procedure cells | Existing durable event history plus native catalog and catalog-free byte parameter readers; native control reads use the current owner and selected artifact generation | New records are written before fitting. Value, operation, source, generation, and composition are checked. Procedure values use the registered arithmetic instruction set. |
| Training and retention | Three append-only stages, paired zero/frozen/trained/clean interventions, replay parents, duplicate clean rebuilds, exact numerical artifacts, independent scorer | Future reads and task decisions must improve over both parameter controls; previously correct retention reads and decisions must not be lost. A valid negative experiment is retained. |
| Structure and budgets | Existing signed owner receives digest-bound split/merge candidates; selected populations can release decoded parameters and wake within a fixed logical budget | Fixed cardinalities and prefix-only alternatives share information. Search/training costs must be counted. Positive-cost synthetic wiring tests do not demonstrate positive measured utility. |
| Multiple nodes and migration | Authenticated bounded TCP image transfer, durable receiver phases, real TaskFlow provider execution, destination owner reopen and current-version checks | Actual process exits at receive/prepare/current/commit boundaries; original frames, process receipts, lifecycle and communication counts. This is Unix loopback qualification. |
| New domains and combinations | Frozen three-stage writes and unseen future compositions; specialization may use completed prefix traces without rewriting the graph | Authored domain labels never enter the trainer/allocator. Recombining the existing three cell types and instruction set is distinct from discovering new semantic types or programs. |

## What is stored in parameters

`learning/worker.py` produces two separate representations under matched
interventions. The catalog arm learns a classifier whose output indexes a value
catalog. The byte arm predicts the length and UTF-8 bits of a canonical typed
value; its serving artifact has no table of target values. The native reader
validates the decoded value before use and can abstain.

Both representations retain address support and lineage. The durable source
ledger, old versions, training data, shared runtime, and shared language encoder
also remain part of the system. Removing a value catalog from one artifact
therefore does not establish system-level compression. The byte arm's numerical
parameters can be larger than the small explicit facts used in this experiment.

Only the semantic and procedure values are parameterized here. Event history
remains a durable, time-addressed record. The procedure cell represents a
registered program (`identity`, `add_bias`, `multiply`, `affine`, `clamp`), not an
unrestricted program generator.

## What may change the active system

Training and topology evaluation produce candidates and evidence. They do not
grant the candidate permission to activate itself. Publication uses the
existing learning-artifact owner; installation requires the independently
verified signed selection. Every native read binds the current owner cut and
the selected bundle generation.

`stage_memory_structure_v9` validates the exact selected digest/generation,
candidate bytes, and split/merge direction before entering publication. A
`NoChange` decision cannot publish. `sleep_selected_memory_v9` releases decoded
parameters while preserving source facts and the selected artifact. The next
authorized read uses the existing bounded wake path.

Migration carries actual image bytes, authenticated sender/receiver identities,
and a version pin. It reuses TaskFlow's provider effect and recovery protocol.
Reopening the target requires the transferred state and a verified selection;
it is not a general-purpose writer lease handoff. See
[`MIGRATION.md`](MIGRATION.md) for exact scope and failure semantics.

## Frozen addressing result

There were two public development selections, each with 42 actual head fits.
Their total is **84 fits**, not just the final candidate's fits. The second
selection used hybrid features and `C=2`. Calibration and held evaluation
performed no fitting or candidate reselection.

| Split / frozen arm | Correct known wording | Unsupported wording routed | Interpretation |
| --- | ---: | ---: | --- |
| V9 independent calibration | 59 / 72 (81.94%) | 1 / 48 (2.08%) | Empirical calibration gate passed; zero wrong known accepts. |
| V9 independent held | 47 / 72 (65.28%) | 4 / 48 (8.33%) | Held quality gate failed. |
| Frozen V8 on the same new held | 39 / 72 (54.17%) | 5 / 48 (10.42%) | Same held wording comparison. |
| Frozen V7 on the same new held | 26 / 72 (36.11%) | 3 / 48 (6.25%) | Same held wording comparison. |

The predeclared gate requires at least 80% known coverage, no wrong known
accepts, and at most 5% unsupported routing. The `serving_admitted` flag in the
frozen model describes calibration only. It is not a claim that held quality
passed and does not grant production final-use authority.

Explicit unsupported-contract rejection contributes materially: on held, the
raw learned model at the same thresholds routes 10/48 unsupported wordings,
whereas the complete policy routes 4/48. The archive preserves both. These are
constructed examples, not independent population samples; their counts do not
establish population-level risk guarantees.

The native suite has 272 requests per arm: 144 known, 96 unsupported, 12 unknown
entities, 8 ambiguous aliases, and 12 conflicting-time requests. Two entity
instances of a wording are not two independent language observations. Native
coverage must be read from its own original receipt, not copied from this
offline table.

## Cost evidence

`learning/resource_monitor.py` samples a fresh child process tree using Linux
`/proc`, retaining PID incarnations, RSS/PSS observations, filesystem logical and
allocated stock, raw samples, direct-child `wait4` usage, and monitor usage. It
preserves missing observations and launch/cleanup errors. Unknown intervals are
not assigned zero cost; an entirely unobserved metric has a null estimate.

RSS/PSS samples are sequential observations, not a simultaneous census or an
exact continuous byte-time integral. Short-lived unobserved descendants and
between-sample peaks cannot be reconstructed. The scorer recomputes the sampled
integrals and keeps those limits explicit. A logical resident budget, sampled
resource report, and complete system cost are different quantities.

Transport receipts separately count actual request/response/frame bytes and
retain failure attempts. Direct diagnostic routing and a full native control
read are two actual calls in the language harness; their costs must not be
described as the cost of one exclusive product read.

## Reproduction and authority

[`evaluation/INPUT_LOCK.json`](evaluation/INPUT_LOCK.json) pins independent
calibration, held language, and continual task inputs. They were authored before
the V9 results. [`fixtures/address-model/PARTS.json`](fixtures/address-model/PARTS.json)
pins the exact frozen model, weight parts, and native fixture. The full raw
addressing archive is in `evidence/addressing/frozen-01`; it includes both public
selection attempts, calibration, held, inputs, source closures, weights and cost.

The CI workflow is `.github/workflows/memory-cell-v9.yml`. `prepare_ci.py`
reconstructs pinned runtime/model inputs without fitting. `ci_verify.py` runs
Python validation, a same-source App Server build, and scoped Rust tests through
`just test`. Formal mode also runs the ignored actual experiments and independent
learning scorers. Raw command output, failures, receipts and artifacts are kept.

The CI `passed` field describes successful execution and evidence integrity,
not scientific acceptance. Read each scientific gate in the corresponding
receipt. No experiment grants final-use authority.

Finalization is a separate same-source workflow: all testing comes first, then
scoped `just fix`, then `just fmt`. Its patch and resulting tree are preserved.
Tests must not be rerun after that final fix/format step.
