# Pretrained catalog strict-validation successor

Base source: `b3fdc981568ab9ce122d2fb569372651e0b4b314` (Draft PR #7187).

This source-only successor replaces all 18 optimizable `assert` statements in
`assets.py`, `encode.py`, and `adapt.py` with explicit fail-closed validation.
The covered invariants include the official model checksum, catalog identity
and coverage, resume-block identity and shape, feature checksums and finiteness,
sealed adapter weights, and development/held-out product uniqueness.

`test_strict_validation.py` parses all three entry points to reject any future
`ast.Assert`, exercises the common validation helper, and starts a separate
`python -O` interpreter to prove that rejection remains active under optimized
execution.

No model, CLIP asset, dataset, feature extractor, adapter, DDE, Torch runtime,
or optimizer is loaded or executed by this gate. It does not change the frozen
protocol, candidates, thresholds, results, or the negative outcomes already
reported by #7187. Scientific qualification and production adoption remain
HOLD.
