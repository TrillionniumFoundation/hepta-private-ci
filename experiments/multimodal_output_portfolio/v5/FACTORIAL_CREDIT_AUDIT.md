# NDU v5 learned factorial: independent post-hoc credit and tail guard

**DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO.** This audit adds no new
training, evaluation worlds, natural decoder, source authorization or
independent signature. It reads the frozen three-seed `development-report.json`
without importing the original training, actor, evaluator, or scoring code.
The report itself was already exposed to development analysis; this is **not**
a preregistered confirmatory gate or proof of causal utility gain.

## Frozen experimental design

Four arms are ordinary supervised training (S) or NDU tail-weighted BCE
training (N), crossed with fixed dev-selected static inference (S) or
six-bin contextual NDU inference (N). The four seed-level decoded losses are
`L_SS, L_SN, L_NS, L_NN`.

Reported contrasts are:
- **Training effect at static inference:** `L_NS-L_SS`
- **Inference effect at supervised training:** `L_SN-L_SS`
- **Inference effect at NDU training:** `L_NN-L_NS`
- **Training × inference interaction:** `(L_NN-L_NS)-(L_SN-L_SS)`

Negative deltas are lower externally decoded synthetic loss. Aggregate only
across three training seeds (17,29,43), **not** 1,536 independent training
replicates or 6,144 independently drawn model checkpoints.

## What the immutable development values imply

| Seed | S/S mean | S/N mean | N/S mean | N/N mean | Factorial interaction |
| --- | ---: | ---: | ---: | ---: | ---: |
| 17 | 1.1953125 | 0.78515625 | 1.083984375 | 0.609375 | -0.064453125 |
| 29 | 0.1328125 | 0.3359375 | 0.1328125 | 0.3359375 | 0 |
| 43 | 1.1796875 | 0.861328125 | 1.158203125 | 0.83984375 | 0 |

- Seed-mean N/N minus S/S **mean loss is -0.2408854167** (descriptive).
- Seed-mean N/N minus S/S **CVaR90 is +0.0520833333** (worse tail).
- Seed-mean N/N minus N/S **CVaR90 is +0.3385416667** (worse tail).
- Mean factorial interaction is **-0.021484375**; its only nonzero
  observed contribution is seed 17, without an independent uncertainty bound.
- Seed **29** becomes strictly worse on mean external loss when switching
  from N/S to N/N (+0.203125), and the result must remain in all rollups.
- **All three N/N arms have refine_rate 0**. Observed differences are mainly
  paid `QUERY` choices, not iterative four-modality generation.
- The four experimental arms have unequal **modeled** realized action cost
  within each seed; no actual end-to-end physical-cost equality is established.

## What the executable gate rejects

`factorial_credit_gate.py` rejects duplicate/missing training seeds,
incomplete four-arm census, fake query rates, incomplete source/Head-call
counts, malformed or nonfinite metrics, CVaR less than the mean, impossible
modeled resource totals, and attempts to change the frozen result's
`DEVELOPMENT_ONLY_HOLD_NO_GO` status. It explicitly returns negative
nonregression, dynamic refinement and cost-equality gates and refuses an
all-blockers-closed assertion.

The `input_sha256` is an integrity hash, not an independent truth or
hardware attestation. Original row-level output identities and scores remain
the separate #3522 independent-observer responsibility; this new gate does
not reauthenticate source lineage. It must not substitute for new natural
source-disjoint heldout, real pretrained four-output generation, independent
terminal outcomes, actual target-device cost, paid verifier calibration, or
prospectively controlled model/critic/actor ablations.

## Replay

```bash
cd experiments/multimodal_output_portfolio/v5
python3 -m unittest discover -v -p "test_*.py"
python3 factorial_credit_gate.py
```

A passing source-level test indicates the adverse claims were **correctly
preserved**, not that the NDU output portfolio passed scientific admission.
