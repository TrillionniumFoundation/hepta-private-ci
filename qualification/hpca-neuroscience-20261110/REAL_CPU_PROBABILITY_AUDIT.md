# HPCA real-model probability audit — exposed CPU LoRA predictions

**Status: HOLD_NO_GO / DENY_ALL.** This is a post-hoc read-only analysis of the
*same* 2026-11-10 eight trained adapters recorded in
[REAL_CPU_LORA_EVIDENCE.md](REAL_CPU_LORA_EVIDENCE.md), not a new model run,
independent reviewer, production effect, or successful neuroscience hypothesis.

## Source, exact identity, and contract

The analysis is pinned to the raw
`real_cpu_clock_v1_RESULT.json` SHA-256
`caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615`.
It reads the original four paired seeds 11, 17, 23, and 29 and evaluates
saved yes/no probabilities (rounded to nine decimals in the original report).
The original pretrained model, training data, adapter files, timestamps,
CPU/I/O/resource receipts and exposed prompts are **unchanged**. The
`real_probability_audit.py` code checks arm/seed completeness, equal
source-event streams and parameter-element budgets, identical parent/arm
evaluation IDs, truth and prompt hashes, probability/decision consistency,
and the original HOLD authority. Altered source archive bytes are refused.

Run without PyTorch or network access:

```sh
python3 -m unittest -v test_real_probability_audit.py
python3 real_probability_audit.py --out /tmp/hpca_probability_audit.json
```

The program calculates negative log-likelihood and Brier scores per prompt,
averages within each seed, then reports the difference **heterogeneous minus
uniform** across paired training seeds. Lower is better for both metrics.
The fixed questions are *shared* across the four seeds; **a prompt is not an
independent training replicate**.

## Reanalysis of existing real-model predictions

| Already-exposed evaluation | Questions | Δ hard accuracy | Δ log loss (heterogeneous − uniform) | Δ Brier | Post-hoc two-sided sign-flip p (log loss) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public B | 4 | 0.0 | −0.0091799223 | −0.0040412579 | 0.25 |
| Operator-written C | 8 | 0.0 | −0.0058623457 | −0.0005349282 | 0.75 |

For all four B pairs and C pairs, classification accuracy is unchanged
between clock policies. But **their probabilities differ**, so equality of
hard accuracy does not establish identical models, equal calibration,
or equivalent performance. On log loss, seed 11 favors uniform on B
(Δ +0.00078854) and C (Δ +0.04257940); seeds 17, 23 and 29 favor
heterogeneous on these *already disclosed* questions. Both post-hoc
enumerations have only 16 sign assignments, and no significance or
equivalence claim is warranted. These p-values do not become valid
confirmatory error guarantees merely by enumerating signs: questions
were already exposed, evaluation was operator-controlled, and four seeds
are too few for reliable generalization. Multiple exploratory contrasts
were inspected; no selection or adoption can be based on them.

The prior conclusion of **zero paired hard-accuracy delta** remains
correct. The new finding is the narrower descriptive observation that
stored continuous scores contain small mixed differences which the
accuracy-only summary obscured. It is **not** an improvement in a real
terminal task, actual utility, task retention, independently measured
cost-adjusted value, or a seven-lineage mechanism result.

## Admission boundary

This offline audit only reads previously published JSON and performs
small local CPU arithmetic; it does not perform forward/backward passes,
credential checks, signed external effect receipt verification, training
or deployment. It does **not** change the original operator's 70.29 CPU
seconds or certify omitted energy, hardware, failed attempts, storage,
network, owner effect or independent future B evaluation. An auditor must
still independently bind exact source/model/config/seed to an original
owner; use a prospectively frozen training A, independent future B,
actual NoUpdate/Adopt, different next task C and cold recovery, with
full costs and multi-seed 2×2 Core×NDU baselines.

**Decision unchanged: HOLD_NO_GO; production authority DENY_ALL.**
