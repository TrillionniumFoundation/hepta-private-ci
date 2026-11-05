# Memory Cell V15: typed memory and verifiable lifecycle research

This directory adds an executable reference for ownership, version publication,
migration, structural admission, and evidence-bound evaluation. It also independently
audits the existing real-model V14 evidence. It is stacked on
`6d2551388ed42355f02afbf528472ee2b4d8488b` / [#4687](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4687).

**Status: research reference; no new neural-memory benefit, physical multi-node
qualification, Rust runtime integration, or production activation is claimed.**

The complete Chinese research report is [RESEARCH.zh-CN.md](RESEARCH.zh-CN.md).
Its architecture permits KV, retrieval, centroid/ridge, shared-encoder heads and
Transformer/LoRA cells. Typed semantics and permissions are independent of the
chosen numerical representation. More cells or parameters are not acceptance criteria.

## Implementation

| File | Purpose |
|---|---|
| `authority.py` | SQLite WAL/FULL authority; signed requests/receipts; exact owner, monotone epoch and bundle CAS; immutable component bytes; source/permission freshness; transfer and reshape state machines |
| `admission.py` | Prospective paired evaluation with the same memory/training-input/executor/budget identities; separate executor instances; independent cluster bounds; complete-cost and retention refusal |
| `integration_tests.py` | Loads verified serialized finite-model bytes, executes the evaluator, and connects its decision to publication; synthetic contract fixture only |
| `authority_tests.py` | Real concurrent processes, process-kill commit boundaries, cold restore, migration and authorization controls |
| `review_tests.py` | Independent adversarial tests, including frozen-input and executor-state counterexamples found during review |
| `audit_v14.py` | Recomputes original Git identities, recorded outputs, costs and utility without rerunning or reselecting models |
| `verify.py` | Runs scoped tests and records exact Python source hashes, test identities, failures, environment and limited process costs |

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

The final local scoped run passed **53/53 cases**: 22 authority cases, 11 paired
admission cases, 19 independent adversarial cases and one verified-bytes integration
case. There were no skips, and Python source hashes were unchanged during execution.
Its 10.238-second wall time is a validation cost, not a model-serving benchmark.
Earlier independent review receipts remain labeled with their own source identities;
the unified `checks.json` is the final local source receipt.

The independent GitHub-hosted Linux run also passed **53/53** at exact commit
`7eac806adfa4e8dc3ebf182788484b3b06ad196f`:
[run 41947667160](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41947667160).
The downloaded artifact ZIP digest, all eight source hashes and the raw test-log
digest were verified. Original CI receipts and acquisition metadata are retained in
[`evidence/ci_41947667160`](evidence/ci_41947667160). Its Python validation wall time
was 1.740 seconds; this is another protocol run, not another efficacy sample.

The local environment lacks Rust/cargo/just and contains only a partial historical
checkout. The required `just fmt` attempt exited 127 (`just: command not found`). No
Rust source changed in this delta and no V15 Rust formatter/native test claim is made.
The dedicated CI workflow checks the reference Python paths, not full-repository CI.

## Remaining qualification boundaries

- All new coordinator process tests run on one Linux host and one authoritative
  SQLite filesystem. There is no replicated consensus, independent monotone witness
  or protection against rollback of the whole authority filesystem.
- Owner identity is an Ed25519 public key. This is not post-quantum authentication or
  proof of a hardware node identity; process-incarnation binding belongs in native
  service integration.
- A receiver signature plus checked bytes is not proof of honest, lasting remote
  storage. Physical-node network partitions, corrupt storage and remote final-use
  fencing still require a real deployment campaign.
- This authority's administrative source writes are not a replacement for a real
  multi-user ingestion policy. Full bundle reads assume a cell-wide ACL; fine-grained
  row ACLs require further partitioning or a separately validated read interface.
- Retaining ancestor dependencies prevents false independence claims. It does not
  perform privacy-preserving parameter splitting, machine unlearning or key erasure.
- `admission.py` assumes trusted measurement and model loading, independent clusters,
  and a frozen prospective experiment. It cannot infer those facts from a digest.
  Its statistical bound covers task outcomes, not uncertain future costs. Deployment
  admission must supply conservative cost estimates or separately bound that uncertainty.
  A hung predictor requires an externally bounded worker; the in-process evaluator
  only counts completed deadline overruns as failures.
- No new long-term language retention, strict full-budget superiority or positive
  learned split/merge result is established. Existing negative evidence remains valid.

Rust integration, true authority recovery, physical multi-device qualification,
matched-budget training, long-term updates and actual energy/full-cost measurement
are the next acceptance stages in the research report.
