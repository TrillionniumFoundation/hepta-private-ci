# Hepta Neural Cell Fabric — P0 physical-mechanism and falsification bridge

**Research-only / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO / NO_MODEL_SELECTION / NO_MAIN_MERGE / NO_FINALUSE / NO_PHYSICAL_SPLIT.**

This is a small, executable **cross-lane evidence bridge**, not another runtime, planner, tool executor or model selector. It does not mutate any of the existing Rust owners. The current `main` ownership remains: `neuron.runtime` for cell signals, `inference.control` for models, `utility.ndu` for registered utility, `learning.plasticity` for next-snapshot proposals, Codex App Server / original Native Worker for session and effects, and original Final-use for last-use authorization. The 4 existing subjects remain system/domain/agent/episode; a cell never mints a fifth subject or a permission.

## What can be physically executed now

- `fabric.py`: physically executes a **synthetic** 16D fixed-feature CPU encoder with a scope/freshness/source/model-bound immutable feature bank. Measures one actual encode forward and N independent Q24 Cell Head dot calls at 64/256/1024/4096 logical Cell sizes. A cached borrower is rechecked for current-use admission; no cross-principal/purpose/modality/source/generation implicit sharing. It is not a pretrained Granite97/mmBERT/Laya421 result and does not authenticate original source owner.
- `science_gate.py`: independent postseal four-arm numerical reviewer with no-change, Split, cheap type-prior, and zero-feature lesion. It rejects altered predictions, incomplete original identities, group leakage and hidden costs. This reviewer always returns `HOLD_NO_GO`, even for apparently good held-out accuracy. It requires an **external** original publisher/label/source and immutable prelabel seal for genuine scientific evidence. The included four-case labels are synthetic unit fixtures, not real model efficacy.
- `fabric.py` NDU candidate: exact finite public-information budgeted Bellman tree and a *separate* scalar short-horizon contraction-residual bound with `q < 3/4`. It is not a coupled/global FBSDE theorem, a trained stochastic Z-head, utility-to-gradient estimator or real task optimality certificate. The no-op/stop option is always mandatory.
- `native.py` and `q24_native.c`: AOT-compiled reviewed fixed **C CPU Q24 dot16** with pinned source SHA, source/binary hashes, private 0700 build output, existing-output refusal, bit-for-bit reference verification, and 500 randomized arithmetic checks. It cannot generate arbitrary code, call OS effect APIs, write executable pages, launch GPU kernels, manipulate other processes, or bypass Final-use. The only admitted program is `PURE_Q24_DOT16`; all UI effects are denied. Physical compiled CPU code ≠ full Native Computer Use.
- `pilot.py`: produces create-only, fsynced 0600 JSON with counted physical forward/head work, cold AOT compiler cost, p50/p95/p99 and explicit disjoint timing scopes. Bench is single-host, sequential and synthetic; it is **not** 4096 concurrent requests, service p99, model learning or equal-MCP performance.

## Reproduction on an isolated Linux CPU

```sh
cd qualification/neural-cell-fabric-p0
python3 -m unittest -q test_fabric test_science_gate
python3 -O -m unittest -q test_fabric test_science_gate
python3 pilot.py --repetitions 16 --output-dir /tmp/new-private-hepta-cell-fabric-run
```

`gcc` must be on PATH for the AOT lane. The source-only contract portion uses Python's standard library. Neither install nor workflow downloads pretrained weights. Do not publish raw proprietary sources, model weights or unreviewed task labels through CI.

## How this composes existing branches without merging their authority

| Existing research | Strict handoff, only after its native owner/CI is qualified |
|---|---|
| #2567, #2579 Stem selection | Replace synthetic `make_synthetic_encoder` with **genuine version-pinned original-model inference** through `inference.control`, retaining its complete source/feature identity; use identical Head budgets and independently held labels. |
| #2490, #2556, #2574 | Apply the four-arm reviewer to authentic unseen publisher/future cohorts; cheap type prior and zero-feature comparisons are mandatory. Existing V8 shows 32/32 decision equivalence with the cheap prior, so NO-GO remains. |
| #2570 token bridge | Admit image/audio/video through qualified separate preprocessing/Projector identity; token shape validity is not semantic alignment or generation. |
| #2563, #2577 NDU | Bridge externally labeled expected utility into true owner NDU contracts. The finite tree + scalar contraction here can be a numerical oracle, never authorization or a generalized FBSDE claim. |
| #1682, #2287, #2401, #2487 | Retain existing 256B typed action ABI and fresh OS readback; pure compiled CPU work may be reused only if approved. |
| #2515 Execution Port | Effects stay with original owner, durable intent, current Final-use, real readback and reconciliation. No second executor or new effect authority. |

## Strict next acceptance gates

1. **Real pretrained** SHA-pinned 47M/97M/mmBERT/421M model+tokenizer/source originals, source-separated fit/cal/held/future windows, matching frozen/learned Head resources, and blind human labels. Independent reviewer must demonstrate that semantic inputs matter **beyond** route-only prior and zero-feature lesion.
2. **Authentic modality necessity** for text/image/audio/video, independently derived timestamps and matched unimodal controls; only then train conditional image/audio/video generators and assess actual decoded artifacts.
3. **Real task NDU outcome** comparing System1, equally budgeted search without NDU, NDU with learned evaluator, and forced cheap/no-change. Freeze objectives and observer before training, count shared work exactly once, and protect existing tasks from regression.
4. **Actual native UI and end-to-end effect** qualification on an instrumented target OS using current identity, scoped expiring capability, exact readback, durable intent, fail-closed recovery and signed Final-use; compare matched Typed/IPC/JSON/MCP end-to-end while counting cold/hot compiler amortization, security checks, GPU driver overhead and failure handling.
5. Independently tested **64/256/1024/4096** concurrent/cached realistic workloads, CPU/GPU/RSS/VRAM/energy/p95/p99/WAL cold recovery plus all Architecture and global `blocking-ci` gates. No waiver, auto-merge or model promotion in this P0 branch.

**Intentional scientific outcome:** This slice answers whether the *mechanisms physically execute and reject invalid state*, not whether Cell Split learns, NDU improves natural-language reasoning, or native code replaces MCP. All such unsupported results stay false/unknown.
