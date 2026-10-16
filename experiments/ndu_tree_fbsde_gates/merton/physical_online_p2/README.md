# P3 — actual Qwen3 thinking-token vs nonthinking Reader experiment

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL. NO PRODUCTION PROMOTION.**

Additive research child of [P2 #2504](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2504). The original P2 no-thinking, greedy Prompt-style comparison remains in its own source branch. This P3 candidate keeps the seven-action original P1 optimization, but uses real Qwen3 thinking for `reason` and non-thinking for `direct`/`verify`, with fixed-seed physical sampling for all actions. It does not silently reinterpret the P2 receipt schema. It neither treats offline precomputed actions as free nor substitutes synthetic fixtures for real model results.

## Fixed public sources

- Pretrained `Qwen/Qwen3-0.6B` **revision `16706fc57485378d4ffaf54139b29ccc66ae08fa`**, explicit file hashes of the downloaded model and tokenizer stored in the frozen plan. Does not load `trust_remote_code`. No claim of the older Hepta 135M Reader, so results **must not** be attributed to that candidate.
- AG News publisher-derived `szhuggingface/ag_news` **revision `98c532231d96ae10e176a909192ecac548949288`**; exact SHA256 of the 1.5k training and official test Parquets are checked before use. Four training samples per bucket/parity (16) and two test samples per bucket/parity (8) selected by a frozen first-occurrence rule; `short` means Unicode length <= 180, not an oracle difficulty label. Parity shards are **not independent publisher families**. Original test has historical public labels and possible pretraining exposure; **zero genuine future windows**. No claim of unbiased prospective generalization or benchmark significance.
- Three action names `direct`, `reason`, `verify`. The direct and reason arms have the *same task instruction*, but distinct Qwen3 `enable_thinking=False/True` hard switches. The `verify` arm is still a **single-pass alternative checking prompt**, not an independent verifier or a second model call. Maximum generated tokens are 12/96/32 respectively. All use pinned seeded top-k 20, top-p 0.95, temperature 0.6 sampling (per Qwen3 recommendations). Raw thoughts are never placed into the scored final answer or review CSV; the visible final span is decoded only after token ID `151668` (`</think>`). If the 96-token budget expires before `</think>`, the answer is empty and scores incorrect. Generated thinking-segment token counts include the closing marker; they are measured compute, not proof of improved reasoning quality. The token/latency reservations are **forecast ceilings**, not guaranteed physical upper bounds, and this pilot does not enforce production admission using them. No tool/network or privileged effect in model responses.
- Exact manifest is `p2_manifest.json`, fixed before any physical inference; tariff is an arbitrary preregistered utility unit/token, not dollars. Training/calibration physical work charged once to acquisition and separately from each on-policy serving arm. Full input+output tokens reported (not only incremental reserved effort), plus model loading, train/serve CPU, wall and p95/p99. No hidden free hardware/cache gain.

## Three-stage hosted causal-order experiment

`hepta-ndu-merton-p2-original-online.yml` executes:

1. **source owner** downloads and hashes public source data; exports TRAIN+label-blind held text in a separate artifact from test gold. Original data remain source-owned, no new dataset labels committed.
2. **Reader worker** downloads **only** the public artifact, physically performs **48** TRAIN `generate` calls to estimate the three action outcomes across 16 tasks, computes all seven P1 selections and fsyncs the frozen plan *before* doing any held generation. It then performs **56 independent held generation calls** (seven policies × eight original tasks), including fresh repeated `direct` calls. Their **precommitted task-wise Latin-rotation schedule** counterbalances arm position rather than always running one policy first. The independent reviewer recomputes this order from the frozen allocation and rejects substituted even-resealed schedules. Every original `generate` invocation gets fsynced start/done records and output digest. Create-only evidence files and newly created journal/output directory entries are also directory-fsynced on the Linux target before downstream physical execution; a directory-sync failure refuses rather than releasing a success record. Partial runs never publish a complete success seal. Training labels are permitted; held labels are rejected at input validation.
3. **review worker** obtains original test gold *after* the model outputs are sealed. It independently reconstructs original TRAIN label outcomes, exact P1 plan, complete generation census, journal, prompt bindings, task scores, actual reported input/output tokens and CPU/wall/p95/p99 for the seven policies. Outputs are a **descriptive** historical public-data comparison, not independent model-host hardware attestation or human semantic adjudication.

P1 `ndu_discrete` and `ordinary_same_profile` use exactly the same fixed objective and must choose identical actions. They are still physically **re-executed** as separate policy arms, not credited with free reused outputs. A difference in model results is stochastic/runtime drift, not an NDU advantage. A difference in internal utility profile vs another arm is not itself an external-task lift.

The GitHub Actions workflow has read-only repository permissions, uses independently run jobs, never writes Git sources or changes production NDU/Neuron/Worker/FinalUse/CNS/CAS. A passing source-only unit test is **not** a physical model result. Hosted CI success cannot by itself establish independent accuracy, causal benefit, hardware provenance, or model selection. Original unredacted traces are short-retention CI artifacts, not repo-published claims.

## Run locally

From repository root, Python 3.13 with the dependencies listed in the workflow, first run source-only tests:

```sh
export PYTHONPATH=experiments/ndu_tree_fbsde_gates/merton/token_portfolio_p1:experiments/ndu_tree_fbsde_gates/merton/physical_online_p2
python3 -m unittest discover -s experiments/ndu_tree_fbsde_gates/merton/physical_online_p2 -p 'test_*.py' -v
python3 -O -m unittest discover -s experiments/ndu_tree_fbsde_gates/merton/physical_online_p2 -p 'test_*.py' -v
```

Physical execution must use separate environments/jobs as described above. Do **not** pass `held-private-labels.json` to the Reader stage or regard an author-supplied `original_pretrained_reader_execution=true` flag as independent proof. The fake-Reader tests deliberately exercise this limitation: checksums and journals verify internal consistency, not authenticated original hardware execution.

Next scientific acceptance requires real source-family/time-disjoint held-out panels, stronger independently qualified Reader reference, blinded judge provenance, observed target-host conditions and total-cost randomized/rotated policy order with several seeds. No `NDU > ordinary Bellman` or Merton/FBSDE learning-effect claim is accepted at this stage.

## P3 incremental scientific controls

This branch deliberately uses new version `hepta.ndu-merton.p3.true-thinking-on-policy.v1`; it must **not** deserialize older P2 no-thinking journals as equivalent. The reviewer checks an explicit immutable runtime profile, registered per-action thought-mode flags, generated-token ceilings, deterministic seed derived only from the frozen public prompt (never held gold), truncated-thought refusal and budget-based failure counts. Each policy still physically regenerates its own selected actions; identical-profile Bellman/NDU allocations do not magically become a capability improvement.

This protocol jointly changes thinking-mode switch and its output-token cap, so it is a **computational investment mechanism** experiment, not isolated causal proof that hidden reasoning alone improves quality. A later equal-cap non-thinking arm and genuine prospective tasks are needed to isolate the mode effect. This is also distinct from a real multi-pass verifier: the `verify` action remains single-pass. The local fake-Reader tests can intentionally forge a pinned model identity and are never external attestation. Real pretrained Reader calls, original publisher scoring and target-host token/cost metrics remain unestablished until exact-HEAD hosted jobs complete.
