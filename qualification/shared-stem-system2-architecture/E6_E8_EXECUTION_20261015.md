# E6–E8: physical shared-Stem fan-out, original real-model conditional routing, global-FBSDE admission

**Research, shadow-only / `DENY_ALL`. Source baseline is #2082 SHA `67c503bd0868af6b319c5528ed6800db6290f991`**, inherited #2065 exact archived evidence and #1923 original NDU deterministic numerical reference. These experiments are independent additive research files. They change no production Neuron/Worker, NDU, original model selector, FBSDE production coefficient, FinalUse, Q24/Q32, objective, signer, blocking CI or source policy. No old in-progress experiment is reset.

## What was ACTUALLY executed locally

- **64 regression tests passed** in normal Python and another **64 passed** in `python -O`. Include E0 resource contract, actual distinct 9,744-param Head CPU arithmetic, scope-safe cache, per-Cell callback/revocation, complete source bytes SHA, source-digest mismatch, false model provenance, prelabel/label separation, original model report/decision tamper, signed-control refusal, exact rational global stitching, and action-gap cost gates.
- On a single un-attested local Linux CPU process, executed **both arms** for 64/256/1,024/4,096 separate FP32 Head banks, **12 complete batches per arm per scale**, identical 8 synthetically generated source arrays, NumPy physical tensor math, CPU clocks and process maxRSS. Every paired cache/non-cache output SHA matched. A separate process independently recomputed **all four scales** from retained raw timings/counts. These are **NOT real pretrained Encoder calls**: NumPy synthetic 384→48→384 projection is used to isolate fan-out mechanics. Production inference latency/energy/training are NOT measured.

| Physical Cell Heads | Actual cached toy Stem calls | Nonreuse toy Stem calls | Cached median batch ms | Nonreuse median batch ms |
|---:|---:|---:|---:|---:|
| 64 | 8 | 64 | 2.397 | 3.348 |
| 256 | 8 | 256 | 6.397 | 10.527 |
| 1,024 | 8 | 1,024 | 28.840 | 44.094 |
| 4,096 | 8 | 4,096 | 127.804 | 188.048 |

**The medians above are local illustrative physical output; hosted CI will produce its OWN clocks, not replace those values with historical numbers.** They include material validation, full actual 9,744-param Cell Head work, and toy projection work. They do **not** prove real 97M/421M Encoder speedup, all-Cell application response p95/p99, GPU/energy, or production safety. The source work and raw observations are separately scoped and not used for model selection.

### E6 exact costs and denial boundaries

- A physically distinct 9,744-param Head is allocated per logical Cell, including a state vector; training is not performed. The 4,096 Heads have 159,645,696 FP32 trainable-weight bytes, matching #2082 analytic accounting.
- Feature reuse occurs **only** for an exact `(scope, generation, stem, tokenizer, normalizer, source, options)` match and only after a fresh callback for **every Cell use**. The callback is a local research allowlist, **not** original authenticated FinalUse. Source float32 bytes are verified against their exact digest on every use. Corrupt source, stale/denied input or duplicate IDs fail closed before output.
- The no-cache arm physically invokes the same toy projection for every Cell and pays the same Cell Head math as the reuse arm. It is a mechanism, not a fair actual 97M model baseline. The actual pretrained Encoder call count is **zero** in BOTH E6 arms.
- `e6_independent_review.py` separately recomputes all reported min/median/max CPU/wall samples, physical tensor byte count, exact 4-scale cohort coverage and expected scoped cache-call counts. It rejects any fabricated production claim. It cannot authenticate hostile runtime clocks or original FinalUse.

## E7 archived REAL Granite/mmBERT route, strictly after the prelabel seal

The dedicated hosted workflow **must** download and verify the exact public original **physical** ZIP 11908591037 SHA-256 `d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa` *before any original labels are present*. The E7 proposer checks both model revisions, original pre-score sealed model reports, same 128 source IDs and their raw probability and per-case time columns; labels are neither imported nor passed. It writes a create-only immutable prelabel action file and pins that file's SHA-256.

Only **after** the file is sealed, a separate step downloads original source labels from historical artifact 11886761368 SHA-256 `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`. An entirely separate scorer loads the original #2065 source-panel validator, recomputes each candidate action from the **original physical** archived outputs, checks exact original group/input digests and computes accuracy, Brier, paired improvement/loss and **hypothetical** secondary calls/archived single-model wall-time proxy.

Five immutable arms are registered *before labels*: `granite_only`, `mmbert_only`, and conditional mmBERT second calls when the Granite maximum binary-class confidence is **strictly below 0.75 / 0.90 / 0.98**. The threshold ladder is not calibrated or optimized on these results and is **not a model recommendation**. Every conditional second model call is charged to the proxy; a cheap first-model call is always charged. Only the original already completed **352 Encoder forwards/model** are historical real execution: this E7 replay adds **zero** new model forwards, and no conditional second-pass worker was physically measured.

This is **same-family retrospective AG News**, not a future-time causal task, not an Encoder winner, not multi-hop reasoning, not natural multimodal inference and not live NDU/Global FBSDE. A report that lacks an artifact or label will fail, not synthesize missing inputs. The frozen historical artifact ZIP bytes, rather than a newly chosen source, are the only eligible external input.

## E8: cost-gated full-horizon mathematical admission

An independent exact-Fraction auditor checks *all* forward dynamics, backward dynamics, both sides of each X/Y interface, a **single** global regular decoupling field, original x0 and the final terminal condition, for the registered scalar deterministic law `dX=Ydt,dY=0,Y(T)=gX(T)`. It distinguishes no solution, nonunique, regular unique and algebraically unique but nonregular. Wrong terminal resets and backward jumps remain **negative controls** even if every individual local segment and final leaf is internally correct. On the hosted workflow `e8_parent_parity.py` MUST cross-check these results against the *original independent #1923* two-sided `stitch_audit.py`. Failure is blocking **for this isolated research job**.

`decide` uses declared, externally sourced **interval utility forecasts** and full incremental cost; a cheap algebraic cost-adjusted gate skips even the toy global audit unless the candidate lower-bound value minus cost exceeds every legal competitor upper bound. On a profitable candidate, the original source/field/endpoints are checked; any global failure falls back. The returned example is a **toy choice only**. These bounded utility forecasts are *not independently calibrated*, the math check's actual CPU is *not separately attested as online cost*, and therefore even a positive toy action result **does not establish incremental System 2 economic gain**. No continuous stochastic/learned neural FBSDE theorem or new owner is asserted.

### Reproduce research without external model weights

```bash
export ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python3 -W error::ResourceWarning -m unittest discover -s "$ROOT" -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s "$ROOT" -p 'test_*.py' -v
mkdir -p /tmp/hepta-e6-physical
for n in 64 256 1024 4096; do
  python3 "$ROOT/e6_physical.py" --cells "$n" --source-groups 8 --trials 12 \
    --output "/tmp/hepta-e6-physical/head-$n.json"
done
python3 "$ROOT/e6_independent_review.py" \
  --inputs /tmp/hepta-e6-physical/head-{64,256,1024,4096}.json \
  --output /tmp/hepta-e6-physical/independent-review.json
# Must run inside the real repo; original #1923 mandatory:
python3 "$ROOT/e8_parent_parity.py"
```

## Required next gate and explicit NO-GO

1. Hosted exact-head E6/E8 source/test/per-profile artifacts and original #1923 math parity successful, including original CI `blocking-ci`/architecture and synthetic-merge gates; no bypass of unrelated failures.
2. Hosted E7 original physical + historical ZIP byte verification, time-ordered source-only seal then independent *original* label scoring; retain raw prediction/cost metadata with no new model inference claim.
3. Independent full-lifecycle measured real pretrained shared-Encoder control, actual 64/256/1024/4096 Worker fan-out, original signed FinalUse and generation/revocation, genuine target-host p95/p99, energy if available, and exact no-change/shared421/97M budgets.
4. Natural, source-disjoint, future-time multimodal/causal Reader tasks with independent task success, OOD/forgetting, and real NDU evaluation. The cheap Bellman/Tree/Critic comparator must be paid as well as all FBSDE certification/Decoder/Verifier costs. If a better solution was reached only via an unaffordable solver, keep **NO-GO**.

**Source status**: local 64+64 fail-closed tests and real synthetic-Head NumPy observations; externally pinned real archive scoring only when the dedicated hosted workflow actually succeeds. `production_accepted=false`, `online_System2_superiority_proven=false`, `real_multimodal_reasoning_proven=false`, `fbsde_general_global_solution_proven=false`, `DENY_ALL`.
