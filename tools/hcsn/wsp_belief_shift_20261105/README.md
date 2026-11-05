# New public-shift and sufficient-state experiments

This package adds two executed, bounded research followups. It preserves the negative digital-feedback confirmation and the failed direct-weight candidates. Nothing here trains, adopts or deploys new weights. The WSP study uses five previously fitted renewal checkpoints; the digital study uses 36 explicitly synthetic fixtures and no fitted checkpoint.

## WSP: what was run

`PROTOCOL_FROZEN.json` was written before the new world scores. It binds the source and 65 input files by SHA256, five fit identities, three new distributions, sample counts, comparison family and resource limits. This is a local prospective freeze following exposure to earlier research, not an external preregistration or independent confirmatory replication. The predecessor is `85f507fb2e1c9e8ad9941451641bb4ec3f1dccb4` (#4823). `planning.py` is byte-identical to that predecessor.

There are 16 new worlds per fit and domain, 240 worlds total, with full expected policy-trajectory evaluation. The public schedule is known to all policies. The target is the moving process sign at deadline six; READ observes the sign at completion. Checkpoint-owned transitions and TRAIN-fitted decoder confusion are available to every structural policy. Evaluator transitions are confined to the evaluator. Schedule hashes are checked against the historical registry, previous compiled-test worlds, and exposed WSP validation/TEST worlds. No validation selection or rejected-world resampling occurs.

| Domain | Changed stressors |
| --- | --- |
| `high_outage` | Failure probability 0.40; delays 1/2; read price 0.03/0.12; repair 0.12 |
| `high_time_price` | Latency price 0.12; read price 0.08/0.24; failure 0.16 |
| `low_signal_cheap` | Reliability 0.51/0.60; read price 0.002/0.02; latency 0.005 |

The five arms are frozen before scoring:

| Arm | Behavior |
| --- | --- |
| C | Unchanged learned continuation scores and learned terminal belief |
| P | C continuation scores, checkpoint-filtered analytic terminal belief |
| Q | Complete own-table Bellman continuation scores, C learned current terminal belief |
| J | Complete own-table Bellman continuation and terminal belief |
| M | One-step own-law lookahead followed by terminal submission, without a neural head |

The C/P/Q/J splice is a **current decision-score decomposition**. Q retains J's complete continuation action-values, including J's optimal future termination decisions; it does not re-solve the future recurrence with the learned terminal score at every future state. These contrasts cannot establish separable causal contributions of two independently trained modules. M supplies a stronger inexpensive analytic control beyond the learned incumbent.

## WSP: retained result, including non-passes

The frozen primary family has nine paired comparisons: J-C, J-P, J-Q in each of three domains. Fits, not worlds or simulated trajectories, are the statistical units: n=5, Student t with four degrees of freedom, Bonferroni familywise 95% intervals. These small-sample intervals depend on the paired-t assumptions. The table reports the original 0.005 margin descriptively; this exploratory package has no model-adoption gate.

| Domain | J-C mean and interval | J-P mean and interval | J-Q mean and interval |
| --- | --- | --- | --- |
| High outage | +0.149563 [0.020514, 0.278612] | +0.137286 [0.048887, 0.225686] | +0.064358 [-0.023061, 0.151777] |
| High time price | +0.307420 [-0.215555, 0.830394] | +0.302184 [-0.243856, 0.848224] | +0.042593 [-0.074240, 0.159426] |
| Low signal / cheap | +0.053541 [0.011847, 0.095234] | +0.034650 [0.017035, 0.052264] | +0.025881 [-0.014784, 0.066546] |

Four of nine interval lower bounds exceed 0.005. All three J-Q intervals cross zero; all three high-time-price intervals cross zero. No global benefit claim follows from the positive means. Interaction J-P-Q+C is positive in 14 of 15 fit/domain pairs, but the sign count is descriptive and the score-splice caveat applies.

Against the stronger myopic M, the mean J advantage is only +0.028378, +0.010796 and +0.028756 respectively. Post-hoc twelve-comparison intervals are [0.000120, 0.056636], [-0.017326, 0.038918] and [-0.000934, 0.058446]. These intervals were added during analysis, are explicitly post hoc, and do not replace the frozen nine-comparison family. No J-M interval clears the original 0.005 lower-bound margin.

## Costs change the interpretation

Three seeded simulated episodes per world/arm measure actual resident-interpreter CPU and wall time. These timers include model/public/table JSON parsing, policy setup and scoring, bounded JSON encoding/decoding, and state transitions. Environment sampling stays outside policy timers. Cold preparation includes exhaustive table compilation, Bellman/probability checks and table serialization; the declared reuse counts are 1, 10 and 100. The implementation intentionally retains its actual setup cost; these are measurements of this Python implementation, not ideal lower bounds or Rust performance.

| Domain | C cold CPU / episode | J cold CPU / episode | M cold CPU / episode | J-C break-even price | J-M break-even price |
| --- | ---: | ---: | ---: | ---: | ---: |
| High outage | 0.013167 s | 0.304560 s | 0.012436 s | 0.513268 | 0.097144 |
| High time price | 0.012124 s | 0.277843 s | 0.012090 s | 1.156935 | 0.040625 |
| Low signal / cheap | 0.013692 s | 0.311519 s | 0.013233 s | 0.179771 | 0.096404 |

Break-even prices are **task utility units per CPU second**, with one-use compilation; they are ratios of sample means, not statistical confidence bounds and not currency. At a price of 0.1 utility units/CPU-second, J loses to M in all three domains on this one-use mean-cost calculation. Reuse amortization changes those crossings; all three reuse scenarios and every raw timer are retained.

The successful WSP execution used 159.982576 CPU seconds and 160.319693 wall seconds, measured from the runner's main body. It is not a full development-cost meter. Prior training amortization, energy, real Owner/media/packet I/O, service overhead and currency valuation are absent. Full economic and production qualification remain false. Files named `not_read_*.json` are public-schema placeholders; no physical packets are consumed.

`verification/verify.py` independently recomputed every raw aggregate and cost equation and used the unchanged predecessor evaluator on 15 worlds × five arms. All 75 utility replays agree within 1.11e-16. That replay took 7.399735 CPU seconds. Its purpose is accounting and evaluator parity; it does not increase the independent fit count.

## Digital feedback: a different, executed state hypothesis

`digital_belief_state/compact_belief.py` replaces the full completed-observation history key of the pinned **static-label** digital task with the posterior probability, tick, remaining budget, broken flag and pending source/due pair. Under the declared fixed binary label and conditionally independent observation law, those quantities determine every future legal action, predictive observation and continuation value. Sunk charges are additive and need not enter the continuation key. The implementation uses exact rational posterior updates over the supplied binary64 emission probabilities, avoiding accidental near-equal float cache keys.

This representation does **not** apply unchanged to the moving-label WSP task, where the latent process state and time matter. It also does not learn a neural state representation or compare new parameter training.

The pinned `reference_task.py` comes from `77b24407b9898aa44769502fbb22c24fb7193a58/tools/hcsn/digital_read_before_20261031/task.py`. The qualifier loads only its unmodified public state/Oracle definitions. The 12 public synthetic worlds and three declared decoder matrices are saved before computation. They are fixtures, not 36 learned fits. Every reachable full nonterminal state is checked, with a 10,000-state/world cap and fixed 1e-10 value tolerance.

| Measurement | Successful r4 result |
| --- | ---: |
| Fixture combinations | 36 |
| Reachable full-state checks | 16,221 |
| Historical cache keys | 13,095 |
| Sufficient-state keys | 5,303 |
| Maximum legal-action Q residual | 7.22e-16 |
| Maximum reference-value regret of compact choice | 2.22e-16 |
| Raw argmax differences | 848 |
| Three cold repetitions × 36, reference CPU total | 3.972579 s |
| Three cold repetitions × 36, compact CPU total | 0.359213 s |
| Whole successful qualifier CPU / wall | 8.144006 / 8.152491 s |

The smaller key set is about 59.5% smaller, and the measured initial-state cold DP calls total about 11.06× faster in this one process. This is a finite implementation result. The 848 raw action differences occur at floating-point ties with negligible reference regret; there is **no bit-for-bit action parity claim**. Timing repetitions are measurements, not additional statistical fits.

Three failed evidence attempts are preserved: strict JSON rejected an illegal-action `-Infinity`; a mistaken class-cache cleanup referenced an instance-bound cache; and an immutable output path collided with an earlier partial result. The final qualifier writes nonlegal Q values as null with a legal mask and requires a fresh output directory. Attempt 1 reached 6.974196 CPU seconds before the failed save. Whole-process CPU for attempts 2/3 was not retained, so complete development cost is unknown. The failed outputs cannot serve as successful qualification records.

The original digital-feedback confirmation remains **0/4 benefit gates and 0/256 full-quality combinations**. There is no new 32-fit retraining, no original-gate closure, and no semantic efficacy or production qualification. The compact prototype is a concrete new state hypothesis ready for a separately frozen efficacy comparison against the existing analytic and ordinary-model baselines.

## Reproduction and evidence map

The archive contains only already-published research inputs. `reproduction/extract_inputs.py` verifies the full archive, all 65 member hashes, bounded sizes and safe regular paths before writing a fresh destination. No live/private model is read. Python 3, NumPy and SciPy are required for WSP; the digital qualifier needs NumPy. Successful executions used one OpenBLAS/OpenMP thread. Use new output directories for every run.

```sh
python3 reproduction/extract_inputs.py --output /tmp/wsp-shift-inputs
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B run_shift_ablation.py --inputs /tmp/wsp-shift-inputs --protocol PROTOCOL_FROZEN.json --output /tmp/wsp-shift-new-run
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B verification/verify.py --inputs /tmp/wsp-shift-inputs --evidence execution_r1 --output /tmp/wsp-shift-verification.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B digital_belief_state/qualify.py --output /tmp/digital-compact-new-run
```

The frozen WSP world bytes, model hashes, raw per-world/per-arm utility, policy traces by hash, sampled actions, timers and familywise aggregates are in `execution_r1/`. The runner retains source identities and the protocol digest, verifies all input hashes, and rejects source changes during a run. The published package manifest binds the frozen source bytes. A replay's new timing differs; semantic utilities should agree within floating tolerance. `digital_belief_state/execution_r4/` is the successful digital evidence; `failures/` holds failed-attempt records. `QUALIFICATION.json` gives the explicit claim boundaries and `PACKAGE_SHA256.json` binds the shipped package.

Next useful experiment: retain M and the stronger analytic controls, freeze new independent fits and distributions, and compare consistent learned-terminal and analytic-terminal Bellman recurrences. A runtime adoption experiment must also measure physical I/O, service costs, and the declared deployment budget. Neither result authorizes a weight edit or a claim of general neural, financial or multimodal advantage.

## Focused repository checks

The unchanged official codespell 2.4.3 checker completed with exit 0 and zero errors on this package. The commit appends only two patterns to the existing skip list: the 16 gzip raw-evidence files and one exact input archive. Source, Markdown and JSON remain checked. The original dictionaries and ignore-word list are unchanged. The 65-member input archive was actually extracted to a fresh directory and every member hash verified. These focused checks do not establish whole-repository CI success; `FOCUSED_CHECK.json` records that boundary.
