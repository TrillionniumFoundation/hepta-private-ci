# Authentic N256 stdlib loader — HOLD

This separately frozen candidate loads the exact new-export-only N256 input
originals already published by Draft #6256. It independently decodes the
canonical base64 ZIP/NPY bytes with the Python standard library, checks every
one of the 1,542 binary64 coordinate encodings against the frozen state JSON,
and validates the eight exact phase packets.

The source imports neither candidate nor oracle code and does not use NumPy,
SciPy, or a matrix-exponential kernel. It closes only the authentic input
decode/binding gap for a future independent reference provider.

## Explicit boundary

This performs no spatial-operator construction, dynamic propagation,
uniformization, matrix exponential, packet continuation, serialization,
Torch, optimizer, or training work. It does not emit the 18,225,028-record
reference stream, provide saved-state byte pairs, satisfy runtime/resource
admission, or qualify N256 dynamics. The export remains new-only and does not
become a recovered historical N256 artifact.

## Retained local development RED

The first local assertions-enabled execution failed before any dynamic or
model work. The NPY decoder compared reversed raw bytes to Python hexadecimal
float strings, and the state-tamper fixture attempted to replace a digest that
is not present in the state original. The retained outcomes were one error
(`N256 state JSON and NPZ coordinates differ`) and one failed expected
exception. The repair changed only representation decoding and the mutation
fixture; it did not change any input digest, count, or acceptance threshold.

Historical RED and UNKNOWN records remain unchanged. Global status remains
`HOLD / NoUpdate / all_closed=false`.
