# HPCA V2 probability-level check — matched, exposed-only

**2026-11-11 UTC — HOLD_NO_GO / DENY_ALL.** This is a post-hoc reanalysis of
the **existing** eight actual SmolLM2-135M CPU LoRA optimizations archived in
[#5905](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5905).
It is **not** an additional training run, independent evaluator, owner-attested
source, or evidence of production eligibility. The training and B material were
publicly exposed; C and calibration were operator-constructed.

The V2 contrast is **bursty minus interleaved**, preflighted in [#5899](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5899).
Both arms used 12 AdamW steps per run, 6 per parameter group, identical
ordered source identities/byte digests/token exposures within each group,
and two AB/two BA execution orders for seeds 11, 17, 23, 29. This
reanalysis checks the matched identity and the per-prompt outcome rows
before calculating any probability score. The four *training seeds* are the
paired units, **not** the 4/8 reused prompts as independent observations.

| Exposed evaluation | Questions | Mean accuracy difference | Mean log-loss difference | Mean Brier difference | Exploratory 2-sided sign-flip p (log loss) |
|---|---:|---:|---:|---:|---:|
| B, public fixture | 4 | 0.0 | +0.00017497129 | +0.00007940722 | 0.500 |
| C, operator questions | 8 | 0.0 | +0.00011125709 | +0.00002091758 | 0.625 |
| Calibration, exposed | 4 | 0.0 | +0.00017374795 | +0.00008022824 | 0.375 |

Positive log-loss/Brier differences weakly favor interleaved on these
**exposed** questions, but the magnitude is tiny, paired seed signs disagree,
and no pre-registered independent analysis supports causal advantage or
equivalence. With only four paired seeds, the sign-flip enumerations are
*descriptive, not confirmatory p-values*. There is no multiple-testing,
independent-source, energy, hardware interference or full-cost qualification.

The old V1 6/6-versus-9/3 frequency comparison was confounded by unequal
group opportunity. This V2 contrast removes that particular count/exposure
confound; it does **not** isolate all relevant causal effects. V2's two arms
still share a public fixture, so neither can establish a real task benefit.
The frozen parent baseline and score row identities are checked across all
paired runs. Unchanged binary accuracy does **not** mean unchanged logits or
probabilities.

## Immutable source and methods

- Parent GitHub source HEAD: [#5905 commit
  `0ed4fce8bd07d361bf7eba40c40fe73d1f349c66`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/0ed4fce8bd07d361bf7eba40c40fe73d1f349c66).
- Raw frozen V2 result SHA-256:
  `9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c`.
  Results contain every paired seed's prompt probabilities, training step
  source identity and measured CPU/wall values; this is an **operator
  archive hash**, not a signature from an independent evaluator.
- Original real model job: heptaruntime `ai395`
  `1a1c87b36af-135c4-9b`, exit 0, eight COMPLETE lines, no stderr;
  separate original reader `1a1c87cf3c2-135c4-9f`, exit 0. These
  job receipts were independently queried again, without restarting runs.
- This audit reuses the existing #5870 fixed-score implementation
  `real_probability_audit.py` for accuracy, binary NLL, Brier and exact
  two-sided sign enumeration; adds V2-specific exact-byte, per-group
  opportunity/exposure, AB/BA, cold-reload and row-identity checks.
- Run `python3 -m unittest -v test_real_probability_audit_v2.py`
  and `python3 real_probability_audit_v2.py --out result.json`. Three
  focused test methods include 10 tampering cases; no new model training.

## Rejected promotion

**HOLD_NO_GO** remains for original owner-attested action/feedback,
actual independent future B, authorized NoUpdate/Adopt, different C
NextUse, cold owner recovery, seven-lineage update rules, delayed ACT/CTRL,
MEM deletion/retention, Core × NDU attribution and complete physical cost.
`NO_UPDATE_RECOMMENDED` is an *analysis recommendation*, not an actual
Owner Selection/NoUpdate transaction. No production weight or permission
change is part of this PR.
