# CTRL 3: frozen, digest-pinned research checkpoints

`metacontrol_checkpoint.py` saves a create-only JSON checkpoint and restores it
only under the expected SHA-256. The loader bounds size and validates schemas,
shapes, finite coefficients, support envelopes, source separation and residual
calibration counts. It does not execute pickle payloads.

The completed mechanism test module adds explicit checks for target-field
rejection, action-specific missing labels, unseen-state fallback, repeated-source
weighting and cold checkpoint integrity. All 14 mechanism tests and 7 study tests
passed together after the final substantive changes; the same head is restored
with the same prediction. Nonfinite derived predictions, oversized coefficients,
inconsistent one-class constants and unknown head fields are rejected.

Calibration records its source digest, row counts and cost qualification; a
snapshot missing that new research contract is rejected rather than upgraded.

Hashes bind supplied bytes, not an external owner's authenticity. Independent
collection and evaluator receipts are still required. Numeric training-envelope
checks are not a semantic distribution-shift detector. The point critic is
fully fitted within its linear model class; broader classes remain an empirical
baseline question. Deployment status remains **HOLD / no-update**.
