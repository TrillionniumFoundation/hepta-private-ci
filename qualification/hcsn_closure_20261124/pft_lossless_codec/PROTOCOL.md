# Lossless fixed-feature statistics codec: prospective protocol

This is a representation-only stage based on `36a2d081c712124c7cd6aecddef35f471d2d6c3a`. It does not modify the peer transport, ledger, numerical solver, training objectives or previous receipts. Register the format and fixed controls before executing them.

## Interface and exact format

New module: `pft_statistics_codec.py`. Public functions are `encode_packet(packet, contract) -> bytes` and `decode_packet(raw, contract) -> packet`. Magic is the eight bytes `HPFTB001`. Accepted encoded packets are at most 8 MiB; an enclosing RPC transport must separately respect its complete-frame limit.

The 114-byte little-endian header has struct format `<8sBHHIB32s32s32s`: magic; flags; feature dimension; output dimension; count; batch ASCII length; contract SHA-256; source SHA-256; payload SHA-256. Flags bit 0 means triangular Gram and bit 1 triangular `yTy`; all other bits are invalid. Dimensions remain bounded at 1..1024 and 1..32; count remains 1..100000; batch IDs use the producer's 1..128 ASCII identifier grammar.

Header is followed by batch ASCII bytes, sorted unique sample IDs as 32 raw bytes each, Gram, RHS and `yTy`, with no padding or trailing bytes. All matrix values are IEEE-754 float64 little-endian. RHS is row-major. A square matrix uses upper-triangle row-major storage only when every mirrored float64 bit pattern is equal; otherwise it uses the complete row-major matrix. Never average, quantize, change a zero sign or infer symmetry from tolerance.

Encoding accepts only the producer's plain Python float matrix entries in correctly shaped lists. Integers, booleans, NumPy scalar objects and nonfinite values are rejected rather than converted. Negative zero, normal finite extremes and finite subnormals are preserved. Existing strict packet/body fields, count/sample identities, contract hash and original payload hash remain binding. The project canonical JSON definition is unchanged.

Decoding checks magic, flags, dimensions, count and exact total length before matrix allocation. It reconstructs the original packet and must re-encode to the same binary bytes; noncanonical modes are rejected. The decoded full object and canonical JSON bytes must equal the original. This also preserves the original float64 bits and existing ledger head identities.

The codec performs representation and hash checks only. It does not certify positive semidefiniteness, source truth, sample authenticity or statistical usefulness. Existing downstream admission checks remain necessary.

## Fixed synthetic controls

1. A fixed 3-feature, 2-output, 4-ID packet includes signed zeros, the smallest positive binary64 subnormal and largest finite binary64 value. Test exact canonical bytes and float64 bits in all four Gram/`yTy` triangle/full combinations, including matrices that are numerically symmetric but have opposite zero signs.
2. Reject integers/booleans and invalid shapes/counts/IDs/contract/hash values; reject NaN and both infinities. Representation controls may deliberately be statistically inconsistent: no PSD or learning claim follows their acceptance.
3. Reject wrong magic, reserved flags, contract/dimension/count mismatch, truncated and trailing bytes, malformed batch lengths, changed hash/data bytes, nonfinite encoded values and a noncanonical full encoding of a bitwise symmetric matrix.
4. Exercise the existing dimension/output/count bounds and reject payloads above 8 MiB. Preserve supported exact-limit metadata without relaxing producer types. No lossy fallback is allowed.

## Fixed historical inputs and measurements

`INPUTS.json` SHA-256 is `2df80f19ad925fe494f4c6306e5c84ea7ccce8ba4c7e1e7f8186611de08745ab`. It binds nine existing `CONTRIBUTIONS.json` files (36 packets) and nine prior candidates used only for their contract/head identities. Their hashes were cross-checked against the #7200 evidence inventory inside archive `f82a4f8d93ee940dff82c2c06a5c9492348bf6f589ae594d538aa40d42f79b28`.

Use every packet in the fixed `n8/n32/n64 × 17011/27011/37011` parent order. For all 36, require exact original payload identity, complete object equality, canonical-byte equality, float64-bit equality and unchanged declared head material. Record each encoded packet, both byte lengths, encoding/decoding time and source hashes. Report the aggregate binary-versus-canonical-JSON byte ratio; no minimum saving is an acceptance gate.

Synthetic controls and the historical roundtrip each get one initial run with a 120-second outer cap. Preserve first failures and source identities; corrections require separately frozen code and separately retained attempts. No automatic retry, model training, new data, final-test access or old scientific-budget rerun is permitted.

Only after the final execution, run required formatting, retain executed bytes and before/after AST equality, and do not repeat tests after formatting. End-to-end network effects belong to a later separately registered transport comparison; byte savings alone are not a training-speed or useful-work result.
