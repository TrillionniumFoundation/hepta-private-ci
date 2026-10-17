# P8 — original Qwen3 conditional reasoning investment (RESEARCH_ONLY / DENY_ALL)

**Draft research stacked on P7 #2620 at exact parent `3fef890e51b7acdf179bad7650a93fffff31f110`.** No P5–P7 source is rewritten, no production model selected, no authority/effect granted, no `main` merge or `blocking-ci` waiver. This is a *new original physical experimental protocol*, **not** a completed physical experiment until exact-head source/model/postseal jobs and independently checked original artifacts exist.

## Distinct observational question

P5 original Qwen3-0.6B public AG News evaluation executed 192 original generation calls, saw 5/16 for both Direct and NDU at slightly higher NDU token cost, and a 96-token `thinking=True` cohort where all 16 reasoning outputs truncated before final answer. P7 independently replayed those exact results, not a prospective out-of-source prediction. This P8 asks whether **after buying a quick initial answer, a limited extra verification investment** improves externally observed success at paid full-model costs, and whether learning a conditional compute allocation beats simple direct/fixed/risk-neutral and *identical objective ordinary Bellman* controls. A negative or null finding is the expected valid scientific outcome.

## New source cohort and physical model

* Reuse **exact same original pinned pretrained** `Qwen/Qwen3-0.6B@16706fc57485378d4ffaf54139b29ccc66ae08fa`, model weight SHA256 `f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b`, tokenizer SHA256 `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4`. The P5 loader verifies bytes before deserialization; only the P8 runtime/prompt profile is newly versioned. No model substitution or pretend physical inference from a fixture.
* Publisher: the same SHA-pinned historical-public `szhuggingface/ag_news` train/test Parquet bytes as P5. **Different original rows**: for each 4 publisher classes × 2 source-text-length strata × 2 original row-index parities, take **second and third** occurrences for TRAIN (32 rows) and the **second** occurrence for HELD (16 rows); the first-occurrence P5 sample is excluded. Rows are selected before any P8 model output. Class-balanced sampling is descriptive and label-dependent at the trusted source owner. It is **not** future-window evaluation, source-family independence, or class-unbiased random sampling.
* Source owner publishes TRAIN + label-blind HELD separately from the original held publisher truth. Reader reads only TRAIN and HELD public packets. After original inference seals, reviewer downloads held truth, re-acquires and byte-compares all original publisher packets. A missing 2nd/3rd source stratum, changed publisher byte SHA, mislabeled source or leaked HELD label is `unavailable`, never silently replaced with a nearby row.

## Two-stage real-budget protocol

For each task and each policy, the original pretrained model is invoked **independently** for a `direct` baseline with `max_new_tokens=12`. The policy sees only observable source-length bucket, the literal parsed / nonparsed direct response, previous **TRAIN-only** outcome/cost table, and remaining *additional checker-call budget*. It chooses `stop`, `check_plain`, or `check_think`. Every selected checker is an additional original physical call and receives the original article plus that same policy's paid first answer. `check_plain` and `check_think` use **identical complete prompts and SHA-derived sampling seeds**, identical `max_new_tokens=256`, but Qwen's actual `enable_thinking=False/True` switch. An unclosed thinking segment has **no final answer**, not a partially correct one; failures and 256 output tokens are fully paid. Real observed prompt + output tokens, request CPU/wall and model cold load are recorded; reserved maximum generated tokens are not claimed to be equal to observed physical compute.

One frozen source and exact policy slate supports six controllers:

1. `direct`: always stop after its own original paid direct;
2. `fixed_plain`: checker on the first four publisher task IDs, paying its own full calls;
3. `fixed_think`: identical first-four schedule at 256 full generated-token cap, but thinking enabled;
4. `neutral`: TRAIN-estimated two-stage belief-state finite Bellman allocation;
5. `ndu_discrete`: same finite Bellman with declared bounded **NDU-inspired** preference/risk weighting;
6. `ordinary_same_profile`: ordinary Bellman with exactly the same information, risk profile and objective as the NDU-discrete arm; exact action parity is required.

Each policy has a maximum of **four additional checker calls across its 16 tasks**, enforced independently. An online exact finite dynamic program integrates the TRAIN-observed valid/invalid prior for remaining known public buckets, not any future HELD responses or labels. Each selected checker must be physically paid at decision time; no precomputed held action slate or caching across policies. Soft risk weights never override hard budgets or allow a forbidden action. TRAIN comprises **96 separately paid generation calls** (32 tasks × direct/plain/think), HELD costs **at least 96 separately paid direct calls** (16 tasks × six policies) plus only chosen checker calls (at most 24). Expected total is **192–216 original physical calls**, not 192 retrospective synthetic counterfactual evaluations.

Expected conditional success and full checker-token charges come from complete paired TRAIN outcomes, with Laplace smoothing and a conservative worst-observed-group profile. Missing TRAIN support cannot select an expensive new checker. The local objective is the *declared discrete finite* surrogate, NOT Merton's continuous-time closed form, a learned FBSDE, or identified causal policy value. `NDU Z`, weight gradients, policy gradients and resource shadow prices are not conflated.

## Provenance, lifecycle and limitations

* Frozen TRAIN coefficients and the entire 16-task **label-blind** public context list are saved as create-only, fsync'd artifacts *before the first HELD model call*. Ordered, hash-linked, fsync'd journal records original start/done for every TRAIN and HELD call and a plan-sealed boundary. Incomplete, missing, swapped, duplicated or mismatched calls reject.
* Separate reviewer replays the six policy decisions from TRAIN, original raw completions, source-separated publisher labels, policy order, full token and CPU/wall bills, true thinking completion, call budget conservation, individual correction/worsening and same-objective ordinary parity. Even a passing reviewer is code-separated rather than an independently authenticated third-party reviewer or billing meter. Full shared training/model-load cost belongs to the entire study and cannot be double-charged per policy.
* Source is historically public, model can be pretrained on similar data, experimental scope is 16 held records and one seed/profile. There is no task-family causal generalization, robust accuracy claim, true financial market/no-arbitrage theorem, production value estimator, self-authorized promotion or verified NDU advantage. Do not report a winning internal recursive utility as external efficacy. Compare actual task success and full observed cost; no reading of unpublished held outcomes by selector.
* Source generation may fail because a required second/third stratum is unavailable. That is a valid hard gate, not reason to relax source selection after observing data.

## Run source-only tests

```sh
D=experiments/ndu_tree_fbsde_gates/merton/physical_online_p8
PYTHONPATH="$D" python3 -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
PYTHONPATH="$D" python3 -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -m compileall -q "$D"
```

All tests use *mock Reader* and constructed mock source. **Passing tests is not evidence of real Qwen inference.** Actual physical execution is configured in the exact-HEAD read-only GitHub Actions workflow. Publisher parquet checks, original weights, online calls and separated postseal scoring must finish; otherwise the truthful result is `not_observed`. GitHub Actions scheduled execution is not a physical pass certificate.
