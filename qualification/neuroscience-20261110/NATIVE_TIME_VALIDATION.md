# Native real-time Q24 execution

Base: PR #6154, `e263e7b01ca051ebc8c15b87ea6b9721169ba22e`.
Scope: numerical mechanism and frozen-prefix binding; **DENY_ALL**.

## Implemented and exercised

The native neuron crate now exposes `real_time_credit`: reward occurrence discount,
state response, update interval and eligibility decay use independent microsecond
parameters. Integer Q48 working precision is rounded to Q24; elapsed time is used
directly, avoiding a per-microsecond decay factor rounding to one forever.
The new frozen adapter verifies clock/boot envelopes before filtering availability,
binds the original model/source/checkpoint/group map, and reuses the existing native
projection, multiplication and clipping order. Future non-time payload is excluded.
The legacy logical-sequence entry point and its nonzero-sequence rule are retained.

Actual command, before formatting:

```sh
just test --locked --offline -p codex-hepta-neuron --lib --success-output final
```

**106 passed, 0 failed, 0 skipped**: 101 inherited tests and 5 new real-time tests.
Rust 1.95.0, nextest 0.9.151; build plus tests wall 16.2244 s, child user CPU
27.8088 s, system CPU 9.4397 s, process peak RSS 328,516 KiB. These are validation
resources, not neural training or task-lifecycle costs. A separate Decimal90
readback recomputed all 11 printed native boundary vectors; maximum integer Q24
error was **0**, against a declared tolerance of 1. This is sampled numerical
validation plus the algorithm's documented bound, not general floating-point
training equivalence or a biological efficacy result.

The local build contains the exact three-crate dependency closure (neuron,
infer-core, types), original crate manifests and original external versions and
checksums. It is not a full checkout. The first `--locked` attempt executed no tests:
the subset lock needed normalization from 49 to 27 packages. No dependency pin
changed; the successful run then used `--locked --offline`.
`just fix --locked --offline -p codex-hepta-neuron --allow-no-vcs` exited 0 and
changed no source; its seven warnings are in inherited test files. `just fmt` ran
from `codex-rs`, exit 0. Per repository guidance, local tests were not rerun after
fix/format; tested and formatted source hashes are both retained. Hosted CI must
independently validate the published formatted source.

## Original evidence and remaining gates

`NATIVE_TIME_EVIDENCE.json` preserves exact original logs, source hashes, build
scope, first refusal, lock normalization, formatter output and Decimal90 readback.
Each payload records byte count and SHA256; decode with
`zlib.decompress(base64.b64decode(payload['data']))` and verify both before use.

Clock identities and source receipts are still caller declarations. Persistent
cadence consumption, original StageOwner attestation, actual model training,
independent B, Selection/NextUse, ordinary C, Root CURRENT and cold recovery are
not established by these tests. No owner key, authority, model or default
architecture was changed. Full-scientific/production status remains **HOLD**.
