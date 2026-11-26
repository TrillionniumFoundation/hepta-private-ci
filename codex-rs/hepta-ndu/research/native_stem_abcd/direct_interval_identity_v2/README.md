# R20 frontier identity v2 candidate

Prepared by static source inspection, then executed once by the root owner on
2026-11-26. All **nine bounded regressions passed** in 0.166694426 seconds. The
frozen original source hashes were unchanged. The actual v2 CLI invocation used
`cap=1` and retained a false global-threshold result, as required by the test.

The original test stderr is 1,464 bytes, SHA256
`d9e86005e78eb7c6bc7fc2e77a31667daea752a79894c31a8190bb9612aa0b9a`.
The root execution result SHA256 is
`f34b1896e945d2c1f7182da80eb1527d1bd5a56b7e2c462849613bee82b0788f`.
This result covers the node-identity repair and bounded CLI route. It does not
requalify a full v2 global bound or transfer the historical eighty-case result.

The frozen v1 solver discards the ID when it pops a node, then reuses the latest
allocation sequence when stopping. Two different retained boxes can therefore
share an ID. Version 2 reinserts the original tuple. Because it immediately exits
the loop afterward, the repair does not change any split, box, pruning decision,
or exact rational bound. The receipt schema is explicitly v2.

## Source and placement

Published against integrated source `ce6b9fe9dcb7d6bb8e78978c8b81a001ac7e2ea2`;
the frozen arithmetic is unchanged from the inspected `1a814b58ac2ef36a567ae2c5edc53cd2f230c13a`.
The legacy `direct_interval/global_interval.py` has Git blob
`e6639540484b4259464e0fdbe1a5f775b31581ec` and manifest SHA256
`6e2e53fa05fd43e5f76d980beabaa765c0e88eb8dce27c682c7b42b507c5c1cc`.
The loader checks both identities before compiling those same bytes. It only
reuses the frozen `cost_bounds`, `bisect`, and `DOMAIN`; the new loop is local.

Proposed repository destination:
`codex-rs/hepta-ndu/research/native_stem_abcd/direct_interval_identity_v2/`.
Place `global_interval_v2.py`, `test_frontier_identity.py`, and this README there.
The default loader then finds the unchanged sibling
`direct_interval/global_interval.py`. For an isolated temporary copy,
set `NDU_R20_LEGACY_SOURCE` to the exact original source file.

Do not edit the original seven sources, historical bounds reports, source hashes,
or `.github/workflows/hepta-native-ndu-direct-interval.yml`. Its path filter covers
`direct_interval/**`; placing this candidate outside that subtree avoids causing
the original eighty-case job solely through this candidate's changed paths.

## Bounded validation for the root owner

The new directory's `test_frontier_identity` uses standard-library unittest.
Its nine tests passed in the execution recorded above. Synthetic exact-Fraction
bounds exercise the one-split old-ID failure, repaired identity, unchanged
mathematical fields, the non-stop
branch, split caps, pruning, and an immediate root stop. A byte alteration checks
the arithmetic-source guard. The only actual, unmocked solver call is a child
CLI invocation capped at **one split** of the real R20 interval objective; its
threshold result is expected to remain false. None of these tests loads a fitter,
Torch, SciPy, or NumPy, or runs an optimizer.

Example after placement, from this new directory:

```bash
python -m unittest -v test_frontier_identity
```

For explicit use by a new candidate, invoke this module, not the old solver:

```bash
python global_interval_v2.py --a 1.54696889 --b .44887401 --cap 1 --out /tmp/R20_V2_SMOKE.json --frontier /tmp/R20_V2_SMOKE.jsonl
```

The output paths must not already exist. This capped command is a route and
identity smoke check, not a fresh global-threshold qualification. Any separately
authorized new complete bounds run must retain its own v2 source identity and raw
frontier; it cannot inherit the v1 eighty-case qualification.

The prepared `hepta-r20-frontier-identity-v2.yml` belongs under `.github/workflows/`.
It runs only these bounded tests on pull requests and main pushes touching this
new directory or that new workflow. It requests read-only contents permission,
uses Ubuntu 24.04 with a five-minute timeout, and installs no dependencies. It
has no manual-dispatch trigger and does not change or dispatch the old R20
workflow. The workflow has not yet been run as hosted CI. This change does not
close broader HCSN scientific, training, or production-admission requirements.
