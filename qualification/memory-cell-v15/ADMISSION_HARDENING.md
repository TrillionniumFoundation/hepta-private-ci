# Evidence-bound admission and isolated execution — 2026-11-05

This increment combines the actual ancestry of native-transition PR #4847
(`4675d776489f1c1f2c832451e44fcd4bad3f583f`) and frozen-cohort PR #4864
(`c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684`). The merge has both commits as
parents. It strengthens the research reference; it does not activate production
Control, train a new language model, or establish economic benefit.

Publication: [draft PR #4885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4885).
The exact-source scoped workflow
[42051127746](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42051127746)
targets `e455cfb761c8e41d8add94a7790e9d0e51fdff2d`. At the retained
2026-11-05 15:19 UTC observation it remained queued; no job had executed and no
artifact was available. Local success is not substituted for this missing result.

## Reproduced problems and corrections

| Problem observed on the recorded predecessor | Current behavior |
|---|---|
| Empty prices and caps approved a synthetic accuracy gain with an arbitrarily more expensive candidate | An explicit cost model, treatment of every resource, and nonempty actual common caps are required |
| Identical arbitrary budget strings passed as equal resources | `budget_digest` binds the actual limits, query deadline and worker envelope |
| A valid-looking ledger could be reused for another data set, workload, cohort or lawful input identity | Receipts bind all of these identities as well as bundle, protocol settings and deployment horizon |
| Different executor closures shared one backing counter; identical models appeared to gain `1.0` | Each arm starts from an independently serialized host snapshot in a fresh interpreter; the same A/A fixture now has gain `0.0` |
| A caller replaced the public protocol after registration, reducing 10,000 planned looks to one | Execution and confidence use the original frozen protocol; the reassignment is reported and refuses admission |
| In-process code could hang indefinitely; launch errors could lose the denominator, and cancellation could leak the worker | Timeouts, worker failures and launch errors retain every registered case in returned results; incomplete arms refuse resource qualification. Host cancellation propagates after owned-worker cleanup; durable cancellation/unknown recording remains the host's responsibility |
| Per-process CPU limits allowed joined children to exceed the declared arm budget | Measured worker plus reaped-child CPU is checked after execution; an overrun refuses qualification |
| Importable callback functions lost their configured module globals in a fresh interpreter | Callback defining modules are serialized by value under a scoped registry lock |
| Historical device verification compared old executions to the latest authority source | Old source bytes remain pinned separately; current checks prove only current source behavior |

The eight admission counterexamples and one positive control use one preserved
probe on both exact predecessor and repaired source. See
[`evidence/cost-admission-20261105/`](evidence/cost-admission-20261105/README.md).
The original counterexamples, independent reviews, normal/optimized test receipts
and historical-evidence review are retained in
[`evidence/admission-hardening-20261105/`](evidence/admission-hardening-20261105/).

The positive control matters: the repaired predicate still accepts its explicitly
qualified synthetic fixture. Rejecting every candidate is not evidence of a useful
admission rule. The probe binds the same synthetic cases, answers, declared caps
and resource vector; only fields required by the new identity schema are adapted.
It is a regression experiment on the predicate, not a model comparison.

## Quality, resource and economic decisions

Reports expose `quality_qualified`, `resource_qualified` and
`economic_qualified`, plus reason lists for each dimension. Publication approval
requires all conditions. The economic flag is deliberately an overall full-cost
qualification: a price calculation does not qualify a candidate with invalid
quality, resource evidence or provenance.

The frozen protocol chooses either resource pricing or billing. It cannot charge
both for the same underlying work. Each resource in the inventory needs a positive
price or a nonempty frozen explanation for its zero price; at least one resource
must be priced. A zero price never makes a missing measurement acceptable.

Receipts bind the candidate bundle; protocol and complete settings; query horizon;
case data; cohort registration; memory, training-input, encoder, decoder, executor
and tool-permission identities; actual common budget; and workload identity.
`cost_binding()` produces expected identity fields. It does not measure resources,
sign a bill or make a caller's accounting truthful.

The full ledger covers acquisition, training, candidate search, update, verification,
serving, restoration and migration CPU; retained byte-seconds; network bytes;
energy; billing; peak RSS and latency. Unknown or invalid values reject admission.
Measured worker CPU/RSS are lower bounds that the supplied full lifecycle ledger
cannot understate. GPU work, external services and other deployment-specific
resources still require measurement and an explicitly extended accounting model;
the current CPU reference is not a universal heterogeneous hardware meter.

All fixture bills are labelled synthetic. In the shared reproducibility probe,
10 serving CPU seconds and 128 MiB RSS are conservative artificial values, with
common caps of 32 seconds and 256 MiB. The worker has its own actual CPU/RSS
measurement. The artificial ledger is not a device cost receipt. There is no new
full-lifecycle energy, storage, network, training or product-utility measurement.

## Isolation and resource scope

`cloudpickle==3.1.2` is used only for trusted host-owned callbacks. Client checkpoints
and network requests must not be deserialized this way. Each arm gets a fresh
Python interpreter, a private temporary working directory and the same initial
host-owned callback state. Callback defining modules are frozen by value; other
imports depend on the pinned runtime and must be controlled by the experiment.

The worker uses POSIX CPU, address-space and output-file limits plus per-query and
whole-arm deadlines. A terminal marker and strict output framing distinguish
completed execution from partial output. Returned failed or unstarted cases remain
in the registered denominator. Host cancellation propagates after process cleanup;
the caller must durably record that cancellation or unknown outcome. The parent
retains the leader PID until group cleanup and
`wait4`, preventing cleanup from signalling an unrelated process after PID reuse.

These are trusted-evaluation controls, not an adversarial-code sandbox. CPU and
address-space hard limits apply per process. Joined-child CPU is a post-execution
check, not a real-time aggregate process-tree governor; aggregate tree memory is
not bounded by `RLIMIT_AS`. Detached descendants, shared absolute files, databases,
remote services and device state require independent snapshots or supervision.
The receipt states these limits explicitly. Parent serialization, package setup,
network and energy are not silently included in its worker resource measurement.

## Preserving historical evidence

The original Mac-to-pocket4 execution remains bound to commit
`386f7a4453b5e59e83db12d8bf958cfb5e4847d0`, its archived source and its original
signed requests, receipts and costs. The source archive is read as data and never
imported or executed. The verifier pins the manifest, archive and individual
SHA-256/Git blob identities and retains the original 16 signed-object checks.

The current source inventory is checked against a separate passing runtime
receipt. Output explicitly says
`historical_receipt_qualifies_current_device_code=false`. Changing archived bytes
and recomputing all mutable metadata still fails against the fixed verifier's
manifest identity. The earlier failed CI remains an observed failure:
[run 41981272551](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41981272551).
No signature or old host execution is relabelled as a new cross-device run.

## Reproduce

Use Python 3.12 and an isolated environment:

```sh
python -m pip install -r qualification/memory-cell-v15/requirements.txt
python qualification/memory-cell-v15/verify.py
python qualification/memory-cell-v15/device_qualification/history_tests.py
python -O qualification/memory-cell-v15/verify.py
python qualification/memory-cell-v15/device_qualification/verify_receipts.py
```

`verify.py` writes to `evidence/checks.*`; preserve each run before another run
replaces those outputs. The scoped CI is configured to preserve both modes, verify
historical receipts and compile the unchanged native subset with Rust 1.95.0.
The runner's test-process resource totals are verification costs, not deployment
costs. See the exact executed-source receipts for counts, environments and status.
The local `just fmt` attempt failed because `just` is unavailable; no Rust source
was changed in this increment. Scoped native formatting/compilation belongs to CI.

## Boundaries still requiring implementation or evidence

- The authority is one SQLite WAL/FULL filesystem. It does not survive rollback
  of that entire authority frontier, provide replicated consensus, or establish
  hardware/PQ node identity. `recover_prepare` handles an unavailable Cell owner;
  it is not authority disaster recovery.
- There is no persistent experiment/look reservation service. The host must
  atomically reserve `(experiment, registration, comparison, look)` before
  dispatch and preserve running, unknown, cancelled and terminal outcomes. A
  new registration cannot legitimately launder an already inspected holdout.
  Frozen settings and a finite union bound do not enforce this across processes.
- Current-time source/permission checks and owner fencing must be connected to
  the native service's actual final-use and external-effect boundaries. The
  dependency-free Rust transition kernel is not that integration.
- The historical finite integer bundle does not exercise a trained Transformer.
  The inspected V14 LoRA checkpoint has weights and AdamW state but lacks a
  separately persisted RNG state and sampler cursor. It cannot prove exact
  training continuation; a newly complete checkpoint needs its own experiment.
  This does not erase V13's earlier full-state small-adapter continuation on three
  CI VMs under its recorded numerical profile; that result does not qualify the
  different V14 checkpoint or the current V15 native service integration.
- Whole-plan split/merge admission, long-term retention and net value still need
  independent future workloads, equal legal information and total budgets,
  strong retrieval/ridge/Head controls, and measured complete costs. More nodes,
  more parameters or more passing protocol tests are not evidence of benefit.
