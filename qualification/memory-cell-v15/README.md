# Memory Cell V15: typed memory and verifiable lifecycle research

2026-11-05 follow-up: the native-transition and [frozen-cohort](COHORT_REPRODUCE.md)
branches are combined. [Admission hardening](ADMISSION_HARDENING.md) binds actual
resource budgets and complete cost receipts, freezes execution settings, isolates
each arm in a bounded worker, and separates historical-device evidence from current
source checks. Historical results below retain their original source scope.

This directory adds an executable reference for ownership, version publication,
migration, structural admission, and evidence-bound evaluation. It also independently
audits the existing real-model V14 evidence. It is stacked on
`6d2551388ed42355f02afbf528472ee2b4d8488b` / [#4687](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4687).

**Status: research reference; no new neural-memory benefit, complete distributed
qualification, Rust runtime integration, or production activation is claimed.**
A bounded, controller-relayed Mac-to-pocket4 persistence and ownership experiment
is recorded separately from the 53-case automated suite.

The current Chinese design and comparison report is
[META_NETWORK_RESEARCH.zh-CN.md](META_NETWORK_RESEARCH.zh-CN.md); the original
report remains [RESEARCH.zh-CN.md](RESEARCH.zh-CN.md).
Its architecture permits KV, retrieval, centroid/ridge, shared-encoder heads and
Transformer/LoRA cells. Typed semantics and permissions are independent of the
chosen numerical representation. More cells or parameters are not acceptance criteria.

## Implementation

| File | Purpose |
|---|---|
| `authority.py` | SQLite WAL/FULL authority; signed requests/receipts; exact owner, monotone epoch and bundle CAS; immutable component bytes; source/permission freshness; transfer and reshape state machines |
| `admission.py` | Frozen prospective paired evaluation; same lawful information and actual common budget; independently reported quality/resource/economic qualification; complete-cost and retention refusal |
| `isolated_runner.py` | Fresh interpreter/private working directory per arm; trusted callback snapshots; per-process CPU/address-space limits, arm deadline, joined-CPU postcheck and complete failure denominator |
| `cohort.py` | Registered candidate roster, phase/source separation, logical source-unit deduplication and finite planned-look correction |
| `integration_tests.py` | Loads verified serialized finite-model bytes, executes the evaluator, and connects its decision to publication; synthetic contract fixture only |
| `authority_tests.py` | Real concurrent processes, process-kill commit boundaries, cold restore, migration and authorization controls |
| `review_tests.py` | Independent adversarial tests, including frozen-input and executor-state counterexamples found during review |
| `audit_v14.py` | Recomputes original Git identities, recorded outputs, costs and utility without rerunning or reselecting models |
| `verify.py` | Runs scoped tests and records exact Python source hashes, test identities, failures, environment and limited process costs |
| `device_qualification/` | Exact-source, controller-relayed Mac-to-pocket4 persistence, cold computation and signed ownership experiment; finite integer fixture only |

The source changes are staged for review: historical audit; paired admission;
authority plus integration; documentation, independent review and execution receipts.
The Python protocol implementation is a reference for later differential validation
of the Rust owner. It is not a second production runtime or an automatic replacement
for existing native components.

## Reference protocol

Every authenticated mutation is serialized at one authority. Signatures cover the
authority public key, actor, operation, full arguments and idempotency key. A repeat
of the same signed mutation returns its historical receipt; reuse of its key with
different bytes is rejected. A historical receipt is not fresh authorization.

All memory/model releases use immutable component hashes. The reference inventory
includes model, memory, encoder, tokenizer, schema, routing, calibration, optimizer,
RNG, sampler and runtime bytes. Hashes establish byte identity. Actual compatibility,
dependency truthfulness and quality require the trusted loader/evaluator.

`publish` checks the current owner, epoch, prior bundle, current sources and effective
ACL. Restoring an old eligible model is a new publication with a larger epoch.
Old source versions or permissions cannot be revived by loading an older bundle.
Permission restriction is separate from a model release; an empty ACL denies all reads.

`prepare` freezes the current cell and advances its epoch. The authenticated receiver
must supply the exact bundle to `ready`; `commit` rechecks the authority state and
sources before switching owner and advancing the epoch again. `abort` restores the
source owner at a new epoch. `recover_prepare` requires the administrator's signature
and the current epoch/bundle CAS, allowing a lost owner to be fenced without its key.

`reshape` atomically retires parents and replaces their exact address partition with
new child cell identities. It supports only a common scope and owner, preserves
complete fitted source dependencies, and uses the intersection of effective ACLs.
A separate trusted whole-plan evaluator is mandatory: individual child approvals
cannot prove routing coverage, combined cost or network utility. All decisions must
bind the complete plan. There is no default beneficial split or merge.

The host-configured evaluator receives verified candidate component bytes. Client
`approved` fields cannot authorize publication. The reference's trusted callback
boundary is explicit: a malicious evaluator or authority administrator can still lie.
The integration fixture demonstrates bytes-to-evaluation wiring, not useful learning.

## What the real-model audit establishes

The audit rechecks **10 fixed Git blobs**, **4,032 recorded outputs**, **504 recorded
composition outputs**, and **42 method/seed groups**. Arithmetic and recorded output
checks agree. There are **zero new model runs or independent language samples**.

On the original 96 semantic requests, LoRA remains `35/39/58`, BERT ridge `62/62/62`,
lexical ridge `81/81/81`, and MiniLM ridge `84/84/84`. The three seeds reuse the same
requests. No prespecified neural candidate wins the original utility comparison at
any of the five original read counts for any seed. See [v14_audit.json](evidence/v14_audit.json).

The original experiment permits different pretrained encoders and unequal resource
usage. It is not a new strictly total-budget-matched comparison. Energy, billing,
complete historical exploration and actual multi-device migration remain unmeasured.
Unknown values are not zero. The exact-string KV in this semantic benchmark is not
the factual-memory KV that scored 192/192 in the separate binding task.

The V14 unrelated-source read-fence bug is already repaired in #4687. Its existing
exact-source native receipt records 19 passed scoped cases. This reference does not
rename that fix or claim those historical Rust tests as new V15 tests.

## Reproduction

Use Python 3.12 and the recorded dependency:

```bash
python -m pip install -r qualification/memory-cell-v15/requirements.txt
python qualification/memory-cell-v15/verify.py
python qualification/memory-cell-v15/audit_v14.py --list-inputs
python qualification/memory-cell-v15/audit_v14.py --input-dir /path/to/full/pinned/checkout
```

The audit also accepts a flat input directory named as shown by `--list-inputs`.
Each file is rejected unless its original Git blob matches. It preserves historical
experimental identities; a change to the audit does not create a new efficacy sample.

`evidence/checks.json` binds the actually tested Python files and lists every executed
test. `evidence/checks.log` preserves the scoped runner output. `verify.py` reports
validation-process CPU/wall/RSS only; these are not memory-service deployment costs.
The positive admission fixtures use artificial resource values and finite selectors.

The original local scoped run passed **53/53 cases**: 22 authority cases, 11 paired
admission cases, 19 independent adversarial cases and one verified-bytes integration
case. There were no skips, and Python source hashes were unchanged during execution.
Its 10.238-second wall time is a validation cost, not a model-serving benchmark.
Earlier independent review receipts remain labeled with their own source identities.
Running `verify.py` replaces its default `checks.*` outputs; retained evidence for
the new increment is under `evidence/admission-hardening-20261105/`.

The independent GitHub-hosted Linux run also passed **53/53** at exact commit
`7eac806adfa4e8dc3ebf182788484b3b06ad196f`:
[run 41947667160](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41947667160).
The downloaded artifact ZIP digest, all eight source hashes and the raw test-log
digest were verified. Original CI receipts and acquisition metadata are retained in
[`evidence/ci_41947667160`](evidence/ci_41947667160). Its Python validation wall time
was 1.740 seconds; this is another protocol run, not another efficacy sample.

After adding the two-host records and independent verifier, exact source
`386f7a4453b5e59e83db12d8bf958cfb5e4847d0` passed the same 53 cases and the separate
offline evidence-verification step in
[run 41950367467](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41950367467).
The downloaded ZIP, source/log hashes and all 16 independently verified signed
objects matched the local records. Original receipts are retained in
[`evidence/ci_41950367467`](evidence/ci_41950367467). CI did not repeat the remote
host operations; it verified their preserved evidence. The later evidence-preservation
commit does not change the executed Python source.

The original V15 local qualification environment lacked Rust/cargo/just and used
only a partial historical checkout. The required `just fmt` attempt exited 127 (`just: command not found`). No
Rust source changed in that original delta; its evidence made no V15 native claim.
The dedicated CI workflow checks the reference Python paths, not full-repository CI.

## Bounded two-host experiment

The configured, SSH-authenticated `mac` (Darwin/arm64, Python 3.9.6) and `pocket4`
(Linux/x86_64, Python 3.14.4) executed the unchanged `authority.py` bytes in isolated
0700 temporary directories. Both used their existing cryptography 46.0.5; no
dependency or service configuration was changed. This validates the exercised
authority subset, not the entire evaluator or Python 3.9 support for the full suite.

The target saved and fsynced the bundle, terminated that process, then used a new
process to load the actual model and memory bytes. Its integer calculation matched
the source: `[[11,10],[1,-10],[14,22]]`. Separate fresh authority processes accepted
`ready` and committed owner transfer at epoch 3. The former owner was rejected even
with epoch 3. The target then signed a modified model publication, accepted at
epoch 4, whose calculation matched the modified parameters.

The fixture contains **408 component bytes**, a **2,276-byte bundle JSON**, and a
**3,632-byte persist request**. These are application payload sizes, not network
wire measurements. Encoder/optimizer/RNG/sampler slots are explicit untrained
placeholders. The run is not a Transformer/LoRA continuation or an efficacy sample.
Keys were generated and used on their owning hosts without export along this run's
path; this is not hardware-backed proof that they cannot be exported.

The controller relayed signed messages; the authority remained on the Mac. There
was no direct peer-to-peer transport, distributed consensus, learned network router,
power-loss experiment or authority-loss recovery. Each worker exited; no new
listening service was installed. Raw phase receipts, independent checks, costs and
reproduction instructions are in [`device_qualification/`](device_qualification/).

## Remaining qualification boundaries

- Each automated reference-suite execution uses one Linux host and one
  authoritative SQLite filesystem. The separate Mac-to-pocket4 experiment still
  uses one Mac authority. Neither provides replicated consensus, an independent
  monotone witness or protection against rollback of the whole authority filesystem.
- Owner identity is an Ed25519 public key. This is not post-quantum authentication or
  proof of a hardware node identity; process-incarnation binding belongs in native
  service integration.
- A receiver signature plus checked bytes, even with an observed later process
  reading those bytes, is not proof of honest, lasting remote storage. Network
  partitions, corrupt storage and remote final-use fencing require further qualification.
- This authority's administrative source writes are not a replacement for a real
  multi-user ingestion policy. Full bundle reads assume a cell-wide ACL; fine-grained
  row ACLs require further partitioning or a separately validated read interface.
- Retaining ancestor dependencies prevents false independence claims. It does not
  perform privacy-preserving parameter splitting, machine unlearning or key erasure.
- `admission.py` assumes trusted measurement and model loading, independent clusters,
  and a frozen prospective experiment. It cannot infer those facts from a digest.
  Its statistical bound covers task outcomes, not uncertain future costs. Deployment
  admission must supply conservative cost estimates or separately bound that uncertainty.
  The current evaluator uses externally bounded workers and counts uncompleted
  requests as failures. This isolates Python heaps and relative working files,
  not external services, shared absolute paths or hostile code. CPU/address-space
  hard limits are per process; joined-child CPU is checked after execution. A
  production aggregate process-tree budget requires additional supervision.
- Registration and settings are frozen within one evaluation object. A persistent
  experiment/look ledger is not implemented: the trusted host must reserve looks
  before dispatch, preserve unknown outcomes and prevent adaptive holdout reuse.
- No new long-term language retention, strict full-budget superiority or positive
  learned split/merge result is established. Existing negative evidence remains valid.

Rust integration, true authority recovery, real-model multi-device qualification,
matched-budget training, long-term updates and actual energy/full-cost measurement
are the next acceptance stages in the research report.

## Native transition increment, 2026-11-05

The new [`native-transfer/`](native-transfer/README.md) increment fixes a reproduced
SQLite counter-exhaustion defect, adds four regression cases (**57 total**), and
ports the five migration transitions into a deterministic Rust kernel for later
Control integration. Exact-source native executables on Mac arm64 and x230 x86_64
matched all **1,536 operation outcomes and complete transfer histories** generated
by the signed Python/SQLite reference in 64 stateful sequences.

The original evidence above remains unchanged. The new kernel is not linked into
the production runtime and does not implement authentication, persistence,
idempotency or full authority rollback protection. These runs do not add a
neural-memory benefit or real-model migration result. The detailed scope and raw
receipts are retained in the linked increment and its qualification record.
