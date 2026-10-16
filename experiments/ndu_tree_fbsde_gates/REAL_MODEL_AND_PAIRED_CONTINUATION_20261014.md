# P0 real-model raw replay + P3/P5 paired System 2 continuation, October 14, 2026

**Research / read-only / DENY_ALL.** This work reuses existing selected-independent research: #1775 real Gemma/Laya pretrained AG News experiment and #1550 exact finite BSDE oracle. It adds **no model loader, new NDU owner, native Neuron action, production activation or qualified stochastic FBSDE**.

## 1. P0 actual real-model upstream observations independently recomputed

Upstream run [38541658096](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38541658096) completed successfully on the then-bound #1775 SHA `f8d168a7689eb3624d97c44751791badd069e521`; artifact **11886761368**, ZIP SHA-256 **e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d**. 128 source-disjoint AG News `new_holdout` cases; public dataset family, **not a prospective future-time cohort**. The artifact includes actual-model reported predictions, model-source receipt metadata, independently produced upstream numerical report, and raw GNU time logs. It does **not** contain physical full model weights, independent source/model signer or independently authenticated Transformer forward counters.

`real_model_artifact_replay.py` reads exact ZIP bytes, checks pinned digest, case/source/input identities and coverage (4 arms × 128), frozen/learned Head metadata, exact checkpoint revisions, every per-arm report digest, 8-bin **predicted-class confidence** ECE, binary accuracy/Brier, paired recovered/lost cases and original GNU time records; it checks the 1024 logit multiplier by recomputation, without fitting. It rejects tampered archives and unsupported promotion claims. The archived raw multi-arm output is **not** used to train a new model in this PR. The source artifact ID is retained for reproducibility; the immutable JSON-only re-scoring result is in `observations/real_model_source_replay_v2.json`.

| Arm | correct/128 | accuracy | Brier | model batch wall allocated microseconds |
|---|---:|---:|---:|---:|
| EmbeddingGemma2 frozen Head | 49 | .3828125 | .25001948 | 27,005,304 |
| EmbeddingGemma2 trained Head | 120 | .9375 | .24881424 | 27,005,176 |
| EmbeddingGemma2 trained + fixed 1024 logit scale | 120 | .9375 | .04932607 | 27,005,176 |
| Laya421 frozen | 124 | .96875 | .02012669 | 65,206,203 |

Paired Gemma learned vs frozen: 75 recovered, 4 lost. Paired Gemma trained vs Laya frozen: **1 recovered, 5 lost**. Neither number proves future-window transfer. Logit scaling improves probability scoring, not prediction accuracy. Scaling was selected on an earlier exploratory panel, not this holdout.

Raw reported process GNU time: Gemma including 40-step Head training **79.01s wall**, **2,097,057,792 bytes max RSS**, Laya frozen **119.12s wall**, **2,999,279,616 bytes max RSS**. These are incompatible lifecycle/optimization work scopes and only single runs. Separate prompt, model, checkpoint, batching, download, repeated-request p99 and independent host conditions were not matched; do **not** call these guaranteed speedup ratios.

Run locally with a freshly downloaded upstream ZIP:

```bash
python experiments/ndu_tree_fbsde_gates/real_model_artifact_replay.py \
  --archive /approved/stem-paired-public-capability.zip \
  --archive-sha256 e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d \
  --output /new/real-model-source-replay.json
```

The archive will eventually expire in GitHub Actions storage; unavailability is a missing observation, not a substitute model result. Do not silently use a different artifact even if its file name matches. Normal unit tests use *synthetic* ZIP fixtures and cannot claim that downloaded weights ran.

## 2. P3: execute an actual learned paired-return Critic, sealed future actions, two separate scorers

This is a **controlled synthetic Bernoulli two-bit public-law task**, not a natural task or a general nonlinear FBSDE. The existing `paired_continuation.py` physically fits one 45-parameter ridge Critic to **4096 training public belief states × 3 actual sampled outcomes**, not labels generated from the exact Bellman value. Public data and independent train worlds are bound before fit. Separate-source-group future_1 and future_2 panels have **512 states each**, actions from four predeclared arms sealed **before** the evaluator samples future worlds:

1. no_search (STOP)
2. fixed_depth_1 (always inspect bit zero)
3. exact_tree (cheap exact Bellman/finite BSDE benchmark using same public law)
4. learned_critic (45-parameter linear estimated continuation)

The code, untrained baselines and all executed work are frozen before independent scoring. The action evaluator runs as a *different process*, opens future hidden-world labels only after action files are sealed, and computes realized as well as exact model-law conditional expected utility. It does not establish cryptographic external owner independence: future random seeds are public and source labels are synthesized. Provenance, objective, no-op, cost and selection barriers remain DENY_ALL.

| Window, n=512 | no_search expected / realized | fixed observe0 expected / realized | exact-tree expected / realized | learned Critic expected / realized |
|---|---|---|---|---|
| future_1 | .561786 / .546875 | .591844 / .587423 | .741178 / .747205 | .736189 / .734925 |
| future_2 | .574283 / .578125 | .600564 / .580208 | .740257 / .714606 | .733705 / .706125 |

**Negative result retained:** learned Critic improves substantially over stop/fixed strategies on this synthetic law but is worse than the cheaper exact Bellman reference on **both** held-out windows. Its extra training, fitting, prediction, scoring and source preparation costs must be counted; no matched-compute superiority, real NDU utility, trained-Cell semantic reasoning or new FBSDE insight follows. A 45-parameter model is not evidence of System 2 emergence.

To replay on the host (NumPy pinned by dedicated CI):

```bash
mkdir /new/paired
OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python experiments/ndu_tree_fbsde_gates/paired_trial_replay.py \
  --output-dir /new/paired --train-count 4096 --future-count 512
python experiments/ndu_tree_fbsde_gates/paired_result_audit.py \
  --directory /new/paired --audit /new/paired_audit.json
```

The replay is create-only. Raw action seal, training samples/realized training targets, independent future scorer receipts and exact source-file digests remain separate. Local submitted summary `observations/paired_two_window_replay.json` is a numerical observation, **not signed evidence of an independent task success**. This PR's Actions workflow regenerates raw evidence on the exact checkout and retains failed attempts. It does not auto-select a winner or activate a Cell.

## Production and scientific blockers

Real Granite97/mmBERT comparison on same locked source and Reader remains missing; real cross-modal tasks, 64/256/1024/4096 physical *Encoder+Head* cells, whole-lifecycle equality, independent external observer, calibrated reader/OOD, source-time-generalization, learned nonlinear FBSDE global well-posedness, and verified future task utility remain unclosed. All owner/module CI and blocking-ci still apply.
