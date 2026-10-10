# Native numeric signal conversion V1

`rescale_signal` converts native row-major `NumericSignalV1` values between
`hnmf-ppm-toward-zero-v1` (scale 1,000,000),
`signed-q24-nearest-ties-even-v1` (scale 2^24), and
`signed-q32-nearest-ties-even-v1` (scale 2^32). These are engineering
conventions, not new production wire registrations. Existing `FixedQ32`
methods keep their original truncation and checked arithmetic.

The target profile controls rounding. The function computes
`raw * target_scale` with checked i128 arithmetic, rounds the magnitude,
restores its sign and checks the i64 result. Overflow or a violated declared
range returns an error; there is no implicit saturation or projection.
Unknown profile IDs reject.

Source and target must have identical shape, unit and normalization digest.
Scalar shape is empty; other shapes have rank at most four, positive dimensions
and at most 4096 elements. The closed signal-unit enum provides dimensionless,
metres, velocity, acceleration and utility units. Additional unit meanings need
an explicit future API extension. This API accepts numeric signals, not exact
authority, identifier, writer-fence, deadline or deletion-state types.

`rescale_signal_registered` is the registry-enforced boundary. Before conversion it requires the shared normalization digest and both source/target `NumericProfileDefinitionV1` records to resolve in the same caller-supplied immutable `ContractRegistryV1`. Each profile definition canonically binds profile identity, definition version, scale and rounding. Missing normalization, an unregistered profile, or a profile semantic mismatch fails closed. Authentication and provisioning of that registry generation belong to the product owner, not to this authority-free library.

Signal and receipt digests use `canonical_digest_v1`, not ad-hoc byte
concatenation. Signal commitments bind profile ID, scale, rounding, overflow
policy, unit, shape, range, normalization digest and raw values. The conversion
receipt binds source/output digests, both profile IDs and the exact maximum
absolute conversion error as an integer fraction in the signal's unit:

`max(abs(source_raw * target_scale - output_raw * source_scale)) /
(source_scale * target_scale)`.

The sum of two receipt bounds bounds round-trip error. Numeric equivalence never
implies byte or digest equivalence. Receipts carry sealed `NonAuthorizingPosture::DENY_ALL`; they do not certify who approved a registry generation, normalization definition, statistical accuracy or deployment. The source-level production-profile admission contract is the exact `NumericProfileDefinitionV1` semantic binding; authenticated product provisioning remains a separate integration gate.

`FixedQ32` shares raw scale `2^32` with `signed-q32-nearest-ties-even-v1`, but its compatibility multiply/divide arithmetic is explicitly `fixed-q32-toward-zero-v1`. Raw-scale equality does not imply arithmetic compatibility.
