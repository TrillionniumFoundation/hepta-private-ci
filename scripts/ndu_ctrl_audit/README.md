# CTRL delivery identity audit (research-only; HOLD_NO_GO)

This standalone, read-only module defines the **minimum receipt consistency**
needed before a WRITE_TEXT content failure can be assigned to selection,
serialization, delivery or evaluation. It does not instrument the actual
#5450 pipeline, and a synthetic PASS is **not** evidence of delivery or score
correctness. Neither labels nor candidate content are included.

Base: #5450 exact head `f6a7d5307f888d30faa8803d23487c78789b99fe`.
Original immutable posthoc diagnostic: 6/6 matching-reference candidates,
6/6 zero terminal scores, and `specific_root_cause_established=false`.
Do not use the diagnostic to manufacture receipt IDs.

## Instrumentation contract

Original stage owners must independently emit, at actual execution time:
- candidate: unique candidate ID and SHA256 of chosen candidate bytes;
- selected: selected candidate ID and byte digest;
- serialized: chosen candidate digest and actual canonical wire-byte digest;
- delivered: same candidate ID, digest of **read-back delivered** wire bytes,
  and an owner-issued delivery receipt ID;
- evaluated: evaluator-bound consumed wire-byte digest, delivery receipt ID,
  candidate ID and observed score.

Each item must be bound to source/tree, task ID, episode ID, run ID,
evaluator version and evidence cut-off by an **owner-attested envelope**.
This v1 consistency checker does not itself validate that envelope or a
cryptographic signature. It must not be used as a production admission gate.

Run: `python audit_delivery_chain.py receipt.json`; failing checks exit 1.
Synthetic regression: `python -m unittest test_audit_delivery_chain.py`
from this directory. Tests cover missing stages, candidate selection,
selected bytes, wire bytes, evaluator binding and malformed score.

## Required actual gate

Collect *all six original* WRITE_TEXT executions with pre-existing source
identities (do not replay against exposed labels as independent confirmation).
Compare each stage, retain mismatch location and original raw receipts,
and separately audit scorer normalization/reference-field logic. If matching
candidates were never selected, this is a selection failure; if selected,
identify the first digest divergence. If all bytes match, investigate
evaluator semantics and score provenance. Preserve UNKNOWN for any missing
receipt. A later independent B set, paid continuation comparison, calibrated
implementation probability, control-value prediction, and matched light
policy are separate gates. No model adoption or claimed policy benefit.
