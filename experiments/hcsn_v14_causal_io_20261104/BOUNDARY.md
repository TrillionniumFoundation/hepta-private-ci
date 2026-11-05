# V14 stage 1: frozen multimodal input boundary

Base: V13 results commit `3b9a136c56e9e743d7ecba852d621e1ecabf6bba`.
The original source, weights, cohorts and negative findings remain unchanged.

`boundary.py` binds text, audio, video and image observations to an immutable
source inventory, source family/session/world, encoder digest and dimensions,
source clock, actual sample window and explicit missing/failure status.
`read_bytes` verifies the exact used source bytes and prevents path escape.
Changing a filename, re-encoding a recording or reusing a session cannot erase
declared historical overlap. Missing history remains UNKNOWN.

The arrival/source clock relation is explicit: an observation can only become
available after `release_offset_ns + end_ns + sync_uncertainty_ns`. This assumes
the supplied clock calibration is valid; the software does not measure it.
`aligned` checks administrative time/source compatibility, not learned entity
recognition. Provenance identifiers must stay outside learned policy features.

All admitted inputs here have role `development`. No new self-authored ledger
can establish the missing original historical custody, fresh capture or model
pretraining purity. The code cannot issue independent-confirmation admission.
The trusted media adapter must crop native samples before contextual encoding
and verify encoder execution separately; packet hashes are not such proof.

Run: `python -m unittest experiments.hcsn_v14_causal_io_20261104.test_boundary`.
The adversarial tests use explicitly synthetic fixtures. They establish byte,
schema, timestamp and provenance behavior, not multimodal recognition quality.
The following stages add durable READ/RESET and frozen V13 model replay.
