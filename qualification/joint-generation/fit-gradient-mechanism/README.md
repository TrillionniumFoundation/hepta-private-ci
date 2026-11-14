# FIT gradient mechanism diagnostic: two negative gates

A finite **post-outcome exploratory FIT-only** probe tested whether a failed
endpoint-aware image-anchor study justified a gradient-conflict intervention.
It did not: **both prespecified diagnostic gates failed**. No retraining, model
selection, threshold relaxation, DEV/TEST access or generation-quality claim follows.

## Actual diagnostic

All twelve trained final states were included: two paired seeds × clipped/endpoint
anchor × S/A/N objective. Before any model load, the probe selected the first
canonical FIT source for each digit, both original noise variants. That is ten
reused sources, twenty requests per model, not 240 independent observations.

One run completed 12 restores, 240 forwards, 960 component backwards plus 240
issued total backwards, and **zero Adam updates**. Text, scaled image, negative
expected-utility and negative conditional-rho2 increments were differentiated
separately; their appropriate sum matched every original objective gradient at
rtol 1e-10 / atol 1e-12. Model parameters and optimizer moments/clocks were unchanged.

- **H1:** an endpoint-trained mode needed both seeds to have more than 10/20
  negative shared-body text/image dot products and median image/text norm ratio
  above one. No S/A/N mode passed both seeds. Endpoint-N had 10/20 and 7/20 conflicts,
  despite norm ratios about 6.82 and 5.30.
- **H2:** at fixed trained-N theta, N needed more text-opposing increments than A
  in both seeds. Neither anchor passed. Endpoint-N had N counts 1/20 and 0/20,
  versus A counts 3/20 and 2/20; clipped-N tied at 2/20 in both seeds.
- Median A/N shared-body cosine by cell was approximately 0.9825–0.9995. This
  describes raw Euclidean gradients, not saved-moment-conditioned Adam directions.

The original study's budget failure and negative quality outcomes remain failed.
The heuristics are not significance tests or causal explanations. A different
mechanism needs a new concrete basis, not an after-the-fact larger sample.

## What this small public package contains

- `mechanism.py`: portable standard-library scalar coefficient formula and frozen
  all-twelve-cell gate checker. It is **not** the private model/backprop engine.
- `test_mechanism.py`: eight finite literal/summary tests. Run
  `python -B -m unittest -v test_mechanism` from this directory.
- `SUMMARY.json`: deidentified aggregate counts, medians and resource summary;
  includes every cell and both negative gates, not selected favorable cases.
- `VALIDATION.json`: separately waited tests of this portable public helper.

No images, source/label IDs, per-request values, model weights/moments, checkpoints,
private input manifests, credentials or machine paths are included. The model/data
execution itself cannot and should not be rerun from this package. Code and summary
publication is not a new experiment grant, deployment, or scientific acceptance.

## Actual resource scope

The complete diagnostic child used 5.354593 CPU seconds, 5.383667 wall seconds and
43,672 KiB peak RSS. It held the original shared exclusive lock, CPU 0 and one
numerical thread; bounds were 30 CPU seconds / 90 wall seconds / 512 MiB.
The supervisor's observed CPU prefix was 0.022556161 seconds; its final tail and
source/review work are unknown, not zero. Portable-helper test cost is additional
and separately reported in `VALIDATION.json`. These are resource receipts, not an
equal-complete-budget or efficacy result.
