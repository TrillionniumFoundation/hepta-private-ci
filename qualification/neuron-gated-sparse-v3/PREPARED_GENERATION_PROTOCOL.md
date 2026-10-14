# Prepared Generation-bound Neuron Q24 Configuration — Shadow Study

**Status: experimental, non-authorizing.** This incremental source branch is
based on `experiment/neuron-five-arm-matched-budget-20261014`, not on the
production `main` route. It must not be used as a signed final-use, artifact
CAS, Cell promotion or deployment acceptance receipt.

## Motivation

The existing V2 public `population_sparse_tick_v2` validates
`PopulationSparseConfigV2` and recomputes its canonical digest on every Tick:
it checks the projection/inhibition graph and copies and sorts each edge set
before hashing. V3, diagonal SSM and low-rank minGRU additionally compute their
own config digests at every Tick.

The existing borrowed temporal override eliminated per-Tick cloning of an
entire V2 config and input, but **did not eliminate the repeated config
validation, hash and edge-ordering work**.

## New sealed configuration objects

| Type | Bound value | Cached per-generation result |
|---|---|---|
| `PreparedPopulationSparseConfigV2` | Owned private complete V2 config | Canonical selected + effective zero-decay digests |
| `PreparedGatedSparseConfigV3` | Owned private V3 config and verified V2 base snapshot | V3 config digest and both V2 base digests |
| `PreparedDiagonalSsmConfigV1` | Owned private SSM time quantum, gains, V2 base | SSM config digest and both V2 base digests |
| `PreparedLowRankMinGruConfigV1` | Owned private factors, gates, V2 base | minGRU config digest and both V2 base digests |

All prepared constructors validate and digest the supplied configuration
**before** accepting any Tick. No public field or mutable accessor can retarget
the copied configuration. A copied old model may be shared by read-only
reference across multiple scoped logical Cells; **their checkpoint state
remains independent**. A new generation, tokenizer/normalizer, frozen Head or
parameter revision requires construction of a **new** prepared object. The
mechanism digest alone does not verify an external model manifest, owner,
signature, native Artifact CAS or independent final-use gate.

On every Tick, both modes still validate the original Q24 input, forwarded
temporary state width and numerical envelope, predecessor full digest,
checkpoint config/scope/objective/body, generation via config digest, increasing
sequence and monotonic clock, plus the downstream deterministic inhibition,
projection, Top-K tie breaks, thresholds, eligibility and receipt.

**Original V1/V2 public functions remain available and retain their replay
semantics.** No V1 journal bytes, known golden vectors or production routes
are rewritten.

## Exact computational equivalence

Rust tests use 64 consecutive signed-Q24 Tick inputs and compare
`(checkpoint, receipt)` for each V2, V3, diagonal SSM and minGRU arm between:

- legacy per-Tick config validation + canonical hash + existing borrowed V2
  temporal override; and
- immutable generation-bound prepared config objects.

One-bit divergence in state, domain-separated config digest, checkpoint
predecessor, original input, auxiliary state or receipt is a failure. Negative
tests exercise mutated source config, changed generations/parameters/time
quantum, stale state, invalid temporal vector, original out-of-bound input,
scope/body drift, sequence gap and clock regression.

These tests are **code-path parity proofs on tested traces**, not an
independent formal proof over all Q24 reachable states.

## Fresh-process, same-host A/B mechanism probe

The `neuron_shadow_mechanism_probe` binary adds:

```sh
--mode legacy
--mode prepared
```

The default is `prepared` in this isolated source branch. The A/B runner
`run_prepared_pair.py` executes 5 arms × 4 Cell scales × 2 modes =
**40 fresh subprocesses** under one GitHub Actions job, alternates execution
order, and verifies each paired `frontier_digest` before reporting descriptive
p99, throughput and process peak RSS ratios.

```sh
cd codex-rs
cargo test --locked -p codex-hepta-neuron --all-targets
cargo clippy --locked -p codex-hepta-neuron --all-targets -- -D warnings
cargo build --locked -p codex-hepta-neuron --bin neuron_shadow_mechanism_probe
python3 ../qualification/neuron-gated-sparse-v3/run_prepared_pair.py \
  --binary target/debug/neuron_shadow_mechanism_probe \
  --trace ../qualification/neuron-gated-sparse-v3/fixture_q24_trace.json \
  --report /out/prepared-pairs.json
```

**Important accounting:** model preparation is deliberately outside the
per-Tick timer. The study measures warm Tick CPU but still allocates both
legacy and prepared config tuples in each process for regression comparison.
Thus the recorded process peak RSS includes the harness, both config forms,
OS allocation and all checkpoints, and must **not** be reported as the
standalone production memory savings of prepared configs. Moreover:
- CI probes run on untrained fixed Q24 fixture drives, not real Encoder + Head
  inference or a workload with a production task distribution.
- One pair per scale/arm is not a calibrated p99 confidence interval; no
  causal throughput or watt/energy improvement is claimed.
- Worker batch, queue fairness, model loading, cold cache, WAL, Artifact CAS,
  CNS, signature verification and OS restart are excluded.
- The paired CI signer, virtual machine provenance and future NDU utility
  remain independent acceptance blockers.

The output hard-codes `NO_PROMOTION`,
`target_host_certified=false`, `ndu_eligible=false` and
`real_training_or_model_efficacy=false`. A failure, mismatch or absent
receipt rejects and does not produce an alternate selected model.

## Promotion remains blocked

Continue frozen no-change A0, exact 2K/8K/16K/64K/262K total model budgets,
same Encoder/tasks/optimization allowances, real pre-label predictions,
future-window NDU utility and negative transfer, independent Evaluator,
Selector and Executor, observed 64/256/1024/4096-Cell end-to-end target-host
resources, WAL/recovery, signed Artifact CAS and generation-fenced final-use.

Only a separately accepted, versioned candidate could eventually be
considered for production; this branch cannot switch any active Cell.
