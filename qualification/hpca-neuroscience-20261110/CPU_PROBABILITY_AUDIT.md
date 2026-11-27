# Real-CPU paired probability-score audit (2026-11-10)

**HOLD_NO_GO.** This is an independent **arithmetic and consistency audit of
retained real-model score records**, NOT a fresh model training/inference run,
owner/source attestation, independent evaluator, confirmation of an effect,
or evidence that heterogeneous clocks outperform strong controls.

## Exact inputs and provenance

- Stacked research parent: HPCA [PR #5739](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5739)
  at HEAD `15daf24ef21e9d038919fef53b82e3a6fb70358d`, original micro tests
  synthetic / HOLD_NO_GO.
- Read-only source: operator-host `ai395`, file
  `~/hpca-real-cpu-clock-20261110-v1/run-11-17-23-29/RESULT.json`;
  **125 KB (124565 bytes)**, SHA-256
  `caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615`.
- Original report declares frozen SmolLM2-135M-Instruct float32 CPU backbone,
  LoRA `q_proj` rank 4; four paired seeds 11/17/23/29, 8 training runs,
  12 optimizer steps per arm. The stored model/config/data identities are
  copied in the derived JSON and are **declarations**, not an attestation.
- The original worker held evaluation B exposed to the experiment operator.
  Evaluation C was constructed by the operator, not prospectively sealed by
  an independent evaluator. Both therefore **fail the independent-future-test
  contract**. The raw archive is retained by the original research worker;
  this PR does not reproduce or silently claim legal rights to republish it.

## Additional score audit

Accuracy rounded to a discrete correct/incorrect decision masked differences
in output probabilities. Recomputing **paired log loss** and **Brier score**
from each saved per-question `p_yes` and actual label (lower is better) gives:

| Reported panel | Mean heterogeneous − uniform accuracy | Log loss | Brier score |
| --- | ---: | ---: | ---: |
| B (exposed; 4 questions per seed) | 0 | −0.0091799223 | −0.0040412579 |
| C (operator-constructed; 8 questions per seed) | 0 | −0.0058623457 | −0.0005349282 |

These are **descriptive differences on the same nonindependent panels**,
not validated scientific improvements. At both panels, 3/4 seed differences
in log loss favor heterogeneous, while the remaining seed worsens. No
significance test or effect threshold is claimed; n=4, label exposure,
selection and repeated opportunity to inspect results preclude that inference.
The real model's meaningful endpoint, resource-matched costs, multi-family
retention, actual ACT/CTRL delayed outcomes, and a complete Core×NDU 2×2
are unmeasured.

The standalone stdlib script rejects: modified source SHA-256; missing,
extra or duplicated arms; mismatched token/parameter-write opportunity;
non-finite or boundary probabilities; headline accuracy inconsistent with
per-question predictions; label/task drift; and cold-reload score drift.
It reports every paired seed and both scoring rules. Raw data stay read-only.

## Reproduce against the original (not a synthetic test)

```sh
cd qualification/hpca-neuroscience-20261110
python3 -m unittest -v test_audit_cpu_probabilities.py
python3 audit_cpu_probabilities.py \
  --archive /path/to/original/RESULT.json \
  --expected-sha256 caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615 \
  --out /tmp/CPU_PROBABILITY_AUDIT_RESULT.json
```

The committed derived result records the actual SHA-pinned run; adversarial
unit fixtures only establish the validator's invariants, not a new efficacy
trial. The path-scoped HPCA GitHub workflow runs the validator tests along
with the original 9 synthetic smoke tests, but CI cannot reproduce the
private model archive and must not claim to.

## Release gate

All of owner-authenticated action/source/feedback receipts, signed training,
prospectively frozen independent B, authorized NoUpdate/Adopt, different real
C and cold recovery, complete compute/label/network/storage/energy/failure
cost, old-task/OOD and typed replay/deletion, and statistically controlled
2×2 Core×NDU comparisons remain **OPEN**. **No model weights, trust roots,
selected cells, policy, FinalUse or production state are modified.**
