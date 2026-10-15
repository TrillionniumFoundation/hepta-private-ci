# Pre-execution admission and sequential stopping

Research-only / DENY_ALL. Extends exact parent `9f4bd1f333ebb64a4d8bd524590ad0bb22e90d4d`
without changing the archived experiment, original Reader or production owners.

## What is genuinely different

The old selector paid 128 SGD updates before choosing the 8-update checkpoint.
This worker owns a new zero-initialized Head per arm, authorizes each block BEFORE
executing it, and never evaluates an unexecuted checkpoint in the controller.
A durable start/decision/train-start/train-done/observation/success journal records
the executed prefix. Interrupted runs have failure or incomplete records, never a
success seal. The audit reconstructs every event from original data and verifies
parameters using the inherited independent scalar SGD implementation.

The same archived mmBERT AG News features and original 64/32/32 split are reused.
There is real new 1540-parameter SGD but no fresh Encoder call. All 32 heldout
records have been examined previously; no untouched-source or prospective claim.
The predictor does not open holdout labels. Source coordinator and reviewer do.
This is data-flow separation, not OS isolation or an independently signed witness.

## Fixed mathematical control, including its limitations

At each available checkpoint, four original calibration block counts define
u_alpha = (1-alpha)*mean(correct) + alpha*min(block accuracy), in [0,1].
For neutral/fixed control alpha is 0/1/4. For NDU-inspired control it starts at
1/4 and, after each actually observed checkpoint, updates by
clip(alpha+(1-2*mean(correct))/8, 0, 1/2). No neural preference is trained.
The ordinary reference applies the SAME rule in a different implementation;
it is not an exact globally optimal Bellman oracle.

Let u_best be the best available utility evaluated at CURRENT alpha, H the
registered reuse scenario, and q the next block's declared training plus
calibration fee. The immediate stop alternative is H*u_best. Even a perfect
next outcome cannot exceed H-q on this finite empirical utility scale.
Consequently H*(1-u_best) <= q is a sufficient rejection rule for any continuation
that must first pay q and has only nonnegative subsequent charges. Hard step
budgets are checked separately. This ceiling is not a confidence bound on future
accuracy, a calibrated expected training ROI, or a proof that model deployment is
safe. With positive headroom the first 8-step block is bounded exploration, not a
claim that starting has positive expected net value.

After a pilot, the continuation estimate extrapolates the previous observed
utility change at current alpha, caps it by 1-u_best, and subtracts only the NEXT
block's charge. Stop on nonpositive net projection; choose the earliest best
ALREADY AVAILABLE checkpoint. Past compute is sunk for continuation choice but
is charged once in the final lifecycle. Plateau-based extrapolation is a
heuristic: a delayed improvement can invalidate it. Unit tests retain such a
counterexample instead of claiming globally optimal stopping.

Protocol tariffs are utility units PER SGD UPDATE and PER calibration call, not
CPU prices or dollars. Report `H*heldout_accuracy - fee_steps*actual_steps -
fee_cal*actual_calibration_calls`; also report raw local CPU separately. Do not
subtract the same tariff twice. H=8 is a declared reuse scenario, not eight new
heldout tasks. High-price and insufficient-budget scenarios exercise refusal;
they are not evidence of realistic economic savings. The old CPU-fee profile is
not reinterpreted. All methods keep the same data, precision and optimizer.

Eight arms, four registered scenarios and three rotated timing repeats yield 96
lifecycles, not 96 independent task panels. Fixed baselines obey the hard budget
but do not acquire calibration or search they never used. Each search arm pays
its own real updates and calibration; no free cross-arm model cache. Timings
include per-lifecycle synchronous journal writes, while shared train-only
normalization, archive preparation and scalar audit are explicitly separate.
CPU and wall counters are self-observed, not external hardware attestations.

## Reproduction

Use Python 3.13 / NumPy 2.3.5, with one BLAS thread. Set `NEWS_ARCHIVE` to the
original archive (SHA `195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7`).
From repository root:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news
python "$D/material_news.py" --archive "$NEWS_ARCHIVE" --output /tmp/seq-material
python -m unittest discover -s "$D/sequential" -p test_online.py -v
python -O -m unittest discover -s "$D/sequential" -p test_online.py -v
python "$D/sequential/online.py" --material /tmp/seq-material --output /tmp/seq-run
python "$D/sequential/audit_online.py" --archive "$NEWS_ARCHIVE" --material /tmp/seq-material --run /tmp/seq-run --output /tmp/seq-audit.json
```

Use new output paths. A source hash is a reproducibility binding, not an
independent observer signature. The scalar audit intentionally reconstructs all
128 steps to validate physical prefixes; that offline reference work is measured
separately and never counted as execution by a stopped policy. This is neither
an original continuous neural FBSDE nor proof of NDU-specific efficacy.
