# P2 — physical on-policy NDU–Merton Reader experiment

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL. NO PRODUCTION PROMOTION.**

Additive child of [P1 #2484](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2484). The earlier P1 exact rational two-budget/7-policy selection remains unchanged. P2 requires actual pretrained Qwen3 0.6B greedy `model.generate` on each independently selected task. It neither treats offline precomputed actions as free nor substitutes synthetic fixtures for real model results.

## Fixed public sources

- Pretrained `Qwen/Qwen3-0.6B` **revision `16706fc57485378d4ffaf54139b29ccc66ae08fa`**, explicit file hashes of the downloaded model and tokenizer stored in the frozen plan. Does not load `trust_remote_code`. No claim of the older Hepta 135M Reader, so results **must not** be attributed to that candidate.
- AG News publisher-derived `szhuggingface/ag_news` **revision `98c532231d96ae10e176a909192ecac548949288`**; exact SHA256 of the 1.5k training and official test Parquets are checked before use. Four training samples per bucket/parity (16) and two test samples per bucket/parity (8) selected by a frozen first-occurrence rule; `short` means Unicode length <= 180, not an oracle difficulty label. Parity shards are **not independent publisher families**. Original test has historical public labels and possible pretraining exposure; **zero genuine future windows**. No claim of unbiased prospective generalization or benchmark significance.
- Three fixed prompts `direct`, `reason`, `verify`, no learned/activated chain-of-thought; reasoning action asks for private consideration and a short final classification digit only. Hard original max output tokens 12/32/32. The token/latency reservations are **forecast ceilings**, not guaranteed physical upper bounds, and this pilot does not enforce production admission using them. No tool/network or privileged effect in model responses.
- Exact manifest is `p2_manifest.json`, fixed before any physical inference; tariff is an arbitrary preregistered utility unit/token, not dollars. Training/calibration physical work charged once to acquisition and separately from each on-policy serving arm. Full input+output tokens reported (not only incremental reserved effort), plus model loading, train/serve CPU, wall and p95/p99. No hidden free hardware/cache gain.

## Three-stage hosted causal-order experiment

`hepta-ndu-merton-p2-original-online.yml` executes:

1. **source owner** downloads and hashes public source data; exports TRAIN+label-blind held text in a separate artifact from test gold. Original data remain source-owned, no new dataset labels committed.
2. **Reader worker** downloads **only** the public artifact, physically performs **48** TRAIN `generate` calls to estimate the three action outcomes across 16 tasks, computes all seven P1 selections and fsyncs the frozen plan *before* doing any held generation. It then performs **56 independent held generation calls** (seven policies × eight original tasks), including fresh repeated `direct` calls. Every original `generate` invocation gets fsynced start/done records and output digest. Partial runs never publish a complete success seal. Training labels are permitted; held labels are rejected at input validation.
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