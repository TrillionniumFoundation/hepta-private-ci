# Immutable-origin receipt correction for the cosine residual study

Date: 2026-10-15.

The fixed cosine-residual experiment has not yet produced a model result. Its
first attempt was cancelled before a job began. Its second attempt exposed a
TRAIN/SELECT cache-scope fixture error before model acquisition. After that
scope correction, run `38662789735` passed every new and inherited regression,
resolved all three exact successful upstream runs, downloaded and SHA-checked
all five fixed input archives, and then stopped before model loading or fitting
with:

```
five_causal_experiments.Invalid: unregistered fixed cosine baseline
```

The failed artifact is `11939960887`, GitHub ZIP SHA256
`31c3446d9d49a07cb775a0b3b0c082fdfc8c54ee46d10b9d83f725581cc36d71`.
Its disposition remains `model_execution_completed=false`. These attempts and
all acquisition/test costs remain visible.

## Root cause

The completed similarity analysis stores the GitHub run/artifact metadata digest
observed when it executed. A later query of the same immutable run can change
fields such as timestamps or artifact-list state, producing a different metadata
digest. The residual dependency receipt therefore did not compare byte-for-byte
equal to the historical receipt, even though all immutable identities matched:

- exact run IDs and attempts;
- exact source commits and workflow paths;
- exact artifact IDs;
- exact artifact ZIP SHA256 values;
- completed/success state.

Requiring equality between two observation-time metadata digests is not a content
integrity check. It makes a valid immutable artifact unusable after mutable GitHub
metadata changes.

## v2 correction

`shared_gate_cosine_residual_trial_v2.py` validates both historical and current
receipts. It requires each metadata digest to be a well-formed SHA256, but permits
their values to differ only after proving the immutable run/source/attempt/
artifact-ID/artifact-SHA identities are identical. It then delegates to the
original validator using the exact historical receipt stored by the completed
similarity analysis. The saved threshold receipt is returned unchanged.

The wrapper changes no scientific input, threshold, donor, label, seed, rank,
optimizer budget or readout. New regressions reject changed artifact bytes, IDs,
runs, sources, workflow paths, attempts, readiness or malformed metadata digests.
A separate workflow and artifact name preserve the two prior failed attempts and
avoid cancellation by unrelated branch pushes.

No Reader call, pretrained update, residual optimization, semantic grade or
production permission is claimed until the v2 exact-source workflow completes.
