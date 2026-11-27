# Actual R5 primary weights

Six 78-parameter nonlinear Stem vectors: Adam and explicit-adjoint trust-exact,
seeds 11/23/47, 8-second nominal CPU cap. These are the original final selected
weights, INCLUDING the negative generalization outcomes, not replacement fits.

Decode `bytes.fromhex(Path(path).read_text())`, verify SHA256.json, require exactly
624 bytes and 78 finite little-endian float64 values, then use the parameter order
in problem.unpack. Whitespace is allowed between byte pairs. This is a research
coefficient vector, not a native selected-model artifact or deployment approval.

All initial vectors, every run's weights, complete scenario outcomes and seals
are retained in the accompanying full conversation archive. No oracle optimum
was used to fit or select these coefficients.
