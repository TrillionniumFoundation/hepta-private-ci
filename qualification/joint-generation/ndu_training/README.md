# TRAIN-only NDU training research

The [single completed TRAIN diagnostic](../runs/codex-cloud-ndu-training-train-d1/REPORT.md)
retains all three seeds and both estimator candidates. It is not independent
confirmation, an accepted dynamic controller, or an open-world multimodal model.
The [protocol](PROTOCOL.md) preserves the original objective, budgets and failures,
and includes an unapproved future confirmation draft. [Source freeze](frozen-train-d1.json).

The executed command was:

```sh
cd qualification/joint-generation
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python3 -W error -m ndu_training.run train \
  --freeze ndu_training/frozen-train-d1.json \
  --out runs/codex-cloud-ndu-training-train-d1
```

Do not repeat it under a new directory. The original output exists and the
runner refuses overwriting it. No validation/formal evaluation command exists.
Read saved results and `audit.json` instead of reconstructing experiment data.
The next step is parent review of the three independent research contributions
and their complete history, followed by any explicitly frozen follow-up decision.

The subsequent [review response](review_followup/REVIEW_RESPONSE.md) independently
recomputes all 72 saved parameter deltas and adds source-hash-bound unit-test logs.
The [confirmation proposal](review_followup/CONFIRMATION_PROPOSAL_V1.md) specifies
a fixed multi-seed/source/timing design, its explicit research-budget increase and
conditional power limits. It has not generated data or run confirmation.

The [saved-aggregate mechanism readout](mechanism_readout/REPORT.md) separates
continuous utility gains, wrong agreement and negative-tail mass. Per-request
probabilities/source maps were not saved in that original experiment.

The subsequently authorized [one-shot TRAIN reconstruction](../runs/codex-cloud-ndu-TRAIN-reinference-d1/REPORT.md)
has completed under its [separate frozen protocol](reinfer_d1/PROTOCOL.md).
It saves every request's probabilities and source map, 32 fixed gradient draws,
and all four service waves. The fixed base CE-anchor control variate reduces
descriptive gradient variance for both A and N; it has not been used for training.
The diagnostic opening marker is consumed. Do not repeat the reconstruction.

The subsequent [fixed complete-budget TRAIN 2×2](../runs/codex-cloud-ndu-CV-TRAIN-d2/REPORT.md)
also completed once, after [source/protocol freeze](cv_train_d2/frozen-d2.json).
CV's full reference/correction cost was charged only to CV systems. The primary
strongest-A screen failed: all12 objective/sampler/seed CV-minus-plain utility
effects were negative. Parameters, Adam states, every new row and all failed
tradeoffs remain. Lower measured gradient variance is not training success.
The [accounting erratum](../runs/codex-cloud-ndu-CV-TRAIN-d2/ERRATUM-20261023.md)
clarifies the shared CV-file hash CPU leak and the before-receipt timing boundary;
the original evidence remains unchanged.
