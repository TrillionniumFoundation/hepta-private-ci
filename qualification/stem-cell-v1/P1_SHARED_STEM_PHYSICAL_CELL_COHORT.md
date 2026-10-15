# P1 physical shared-Stem + sparse Cell cohort: equal-model cache counterfactual

**2026-10-15 · research-only / DENY_ALL.** Child of [#2128](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2128) on the exact shared-Reader Stem-fanout owner branch. Reuses its validated `context_claim` / `validate_context` schema. This is an **isolated toy-model physical study**, not a new inference owner, a registered Stem selector, a live 4,096-Cell Worker, a new data authority, an NDU solver or an auto-CellSplit route. It must not be used to promote weights, grant FinalUse or claim 10T / 100T equivalence.

## Scientific question

Can *one physically shared frozen Stem instance* produce identical downstream logits for an actually resident population of 64/256/1,024/4,096 independently parameterized state-gated Heads while saving Encoder forwards **only when source evidence may genuinely be reused under the same scope and identity**? Does selective local SGD update active Head weights without modifying dormant Heads or the frozen Stem?

This extends the earlier isolated `reader_support_fanout.py` (shared evidence features + the same frozen Reader), and it is distinct from [#1926](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1926), which had already physically measured 4,096 stand-alone Head computations. The increment puts an actual frozen Stem, scoped source cache, real packed Head forward, direct unbatched Head control, and per-Cell sparse SGD into **one measured CPU experiment**. It does **not** execute real Granite97, mmBERT, Gemma, Laya, a 421M model, natural language QA or modality generation.

### Declared model and cohort geometry

- Stem: **147,840 parameters**, an actually invoked seeded but **randomly initialized** FP32 `Linear(384,384)` including bias. The same immutable tensors are used in the uncached and cached arms. This is a deliberately weak mechanics-only encoder.
- Each independent Cell has **9,744** physically resident FP32 trainable scalars: `down: 8×384`, `gate: 8×64 + 8`, `up: 384×8`, `output: 8×384 + 8`, matching the output-side gated-Head geometry from #1885. All six weight tensors are actually initialized and kept resident for **all** logical Cells.
- Physical Cell population N = 64, 256, 1,024, 4,096; deterministically select approximately 10% active (minimum eight). Each active Cell executes the frozen Head with a distinct **64-dimensional local state**, while the selected approved evidence may share one frozen 384-dimensional Stem output.
- Sparse learning: two real Torch CPU SGD steps for selected active rows only; sum of cross-entropy over synthetic deterministic 8-class labels, train-only. Full dormant Head weight byte hashes are computed before/after the active-row scatter; an actual learned-logit change is required. The shared Stem never receives gradients. The initial/final training loss and number of changed scalars remain descriptive (no true future-task generalization).
- Packed Head math (`torch.bmm`) is independently compared with ordinary single-Head `torch.nn.functional.linear` for three selected positions. The noncached and cached Head predictions must match **bit-for-bit** for all active Cells.

### Required counterfactual arms

| Arm | Actual source relation | Authenticated claim that may be made |
| --- | --- | --- |
| `repeated` | Four exact source groups repeated across active Cells, **one research tenant** | Scoped cache can reduce physical Stem forwards if enough budget, without changing any logits |
| `distinct` | Every active Cell uses a different actual 384D source vector | **Zero** feature hits; caching cannot be credited with reductions |
| `two_scopes` | The same four source groups occur under **two research principals** | Identical evidence cannot cross the principal boundary; eight separately keyed features if cache fits |

There are **two physical encoding paths per arm**, with identical weights, data and active Cell roster: a no-cache baseline that really calls the Stem once per active Cell, and a bounded source/scope/generation/epoch/model/tokenizer/input-byte identity cache that really reuses its feature tensor when permitted. A caller-provided access check runs for **every logical borrow**; it is only a research hook, not an issuer or signed FinalUse. One-shot source vectors are seeded and **not licensed public data**. Synthetic classes are made from case IDs, not independent outcomes.

**Do not call 4,096 logical resident Cells 4,096 active forwards.** At 4,096 population, 409 are active in this declared fixed ~10% pilot. The all-Head FP32 payload is precisely 159,645,696 bytes (about 152.2 MiB), not the total process RSS. Cache storage, gathered activations, Python overhead, optimizer state, native Q24/Q32, Worker queue, generation/runtime state, model load, energy, p95/p99 requests and audit costs are **not contained** in that payload number.

### Actually executed local CPU controls (one host, not independent source/target proof)

| Physical resident Heads | Active Heads | Uncached Stem forwards | Repeated input, sufficient cache | Distinct inputs, sufficient cache | Two tenants, sufficient cache | Total FP32 Head weights |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 8 | 8 | **4** | **8** | **8** | 2,494,464 B |
| 256 | 25 | 25 | **4** | **25** | **8** | 9,977,856 B |
| 1,024 | 102 | 102 | **4** | **102** | **8** | 39,911,424 B |
| 4,096 | 409 | 409 | **4** | **409** | **8** | 159,645,696 B |

Every entry counts actual `SmallFrozenStem.forward` calls inside the bounded CPU program, *not* tokens/s, a pretrained 421M Transformer execution or a complete service request. All active Heads run on both baseline and reused source features; exact frozen logit SHA and up-to-1e-5 independent-unpacked numerical check are recorded. Every active Head optimizer and dormant-parameter check actually executes; each complete run retains original counters and failure flags. Run outputs must never be interpreted as a universal compression ratio: savings scale directly with **observed true source reuse**, which can be zero.

**Negative budget controls (N=256)** must also succeed and be retained by the independent reviewer:

| Equal cache budget per arm | Repeated Encoder calls | Distinct | Two tenants |
| ---: | ---: | ---: | ---: |
| 0 B | 25 | 25 | 25 |
| 1,536 B (one feature) | 25 | 25 | 25 |
| 6,144 B (four features) | 4 | 25 | 25 |
| ≥12,288 B (eight features) | 4 | 25 | 8 |

A cache budget insufficient for the repeated source cycle may add hashing / checking overhead **without saving any Encoder calls**. This is a legitimate negative result, not an invalid science fixture. `shared_stem_population_review.py` independently checks the complete three-arm roster for each fixed N and **equal per-arm cache budgets**, raw physical counter arithmetic, the full resident parameter geometry, independent-Head inference tolerance, actual active-step and dormant-state claims, and keeps null/negative observations. It is stdlib-only and deliberately never authenticates real host telemetry or signs independent outcomes.

## Running the experiment

With the complete inherited research source tree, Python 3.13 and Torch 2.10.0 CPU:

```bash
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_shared_stem_cell_population.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_shared_stem_cell_population.py' -v

mkdir -p /tmp/p1-population
for n in 64 256 1024 4096; do
  for mode in repeated distinct two_scopes; do
    python qualification/stem-cell-v1/shared_stem_cell_population.py \
      --cells "$n" --distribution "$mode" \
      --cache-bytes 33554432 --seed 7347 --steps 2 \
      --output "/tmp/p1-population/$n-$mode.json"
  done
  python qualification/stem-cell-v1/shared_stem_population_review.py \
    --repeated "/tmp/p1-population/$n-repeated.json" \
    --distinct "/tmp/p1-population/$n-distinct.json" \
    --two-scopes "/tmp/p1-population/$n-two_scopes.json" \
    --output "/tmp/p1-population/$n-audit.json"
done
```

Create-only output paths refuse overwrite. For a **full negative budget panel**, run the three modes at equal `--cache-bytes` of 0/1536/6144 and submit each triplet to the same independent reviewer; it must **accept** legitimate zero savings. The separate, read-only GitHub Actions workflow reexecutes source-bound tests, all 12 complete-cohort fresh-process runs and the negative-budget panel, preserving failure logs and immutable count reports via Actions artifacts. The workflow cannot turn a submitted SHA string into an independently signed publisher/model source or convert toy Cell labels into real QA evidence.

## Next actual model gate — not completed here

Reuse the **original, pinned** real Granite97/mmBERT/421M checkpoint-owner execution from #2065/#2080. First independently certify the original Reader evidence sufficiency and genuine query/answer sensitivity. Then use an actual shared immutable Encoder feature and real source-disjoint data for 64/256/1,024/4,096 Cell tasks, measuring current host CPU/GPU, p50/p95/p99 on *full requests*, cold weight load, KV/feature lifetime, training, artifact checkpoint/rollback, source revocation, native Worker/CAS/FinalUse and independent future task correctness. Compare fixed Router, equal-total-param unsplit Head, independent full 421M copies, and the one-physically-shared-421M baseline **without convolving parameter cost with model quality**. NDU remains cost-gated vs cheap Bellman/Critic/tree/ordinary-optimizer controls, with future utility, not a theoretical Cell count, deciding investment.

**Disposition:** `production_authorized=false`, `actual_4096_real_worker_executed=false`, `model_quality_gain_established=false`, `independent_future_task_utility=false`, `signed_final_use_verified=false`. This read-only research work grants **no** new Hepta capability, and does not merge, deploy or promote anything.
