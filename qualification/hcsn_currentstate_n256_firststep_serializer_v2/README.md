# N256 first-step packet-output serializer v2

Status: **PASS_SMALL_STDLIB_SOURCE / HOLD_N256 / all_closed=false**.

This isolated successor to Draft #6610 fixes only the newly exposed serializer
source defect. The old `HCSNFSP1` format stored packet alpha and operator bytes
but omitted packet output vectors. The new incompatible `HCSNFSP2` schema stores
explicit little-endian FP64 alpha, generator, and output tensors, binds their
shapes, and includes every output value in canonical coordinate rows.

Small stdlib fixtures verify byte and coordinate-row roundtrip, output mutation,
missing and dimensionally inconsistent output rejection, v1 rejection,
corruption/size/trailing-byte rejection, and atomic publication. They construct
no N256 state and perform 0 N256 serialization, dynamics, matrix exponentials,
Torch calls, or optimizer steps.

The first local test invocation is retained in `DEVELOPMENT_RED.json`: 6/7
passed and the atomic-publication test compared the decoded envelope directly
to a fixture whose metadata did not yet contain the canonical schema injected
by encoding. The serializer bytes and coordinate rows were not implicated. The
minimal test-only correction compares re-encoded bytes and coordinate rows.

The authentic warm-1 target still requires 2,600 state, 1,320 packet-alpha,
65,544 packet-generator, and 264 packet-output coordinates (69,728 total). This
source does not serialize those originals. Candidate/oracle/comparator/runner
sources and all resource-admission fields remain null. Historical RED/UNKNOWN,
C2 full replay 0/6, HPCA NoUpdate/external custody, equal-budget benefit,
asynchronous complete cost, production adoption, and `all_closed=false` remain
unchanged.
