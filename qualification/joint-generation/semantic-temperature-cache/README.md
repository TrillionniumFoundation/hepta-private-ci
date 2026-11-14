# Same-law immutable command-map cache

The explicit `immutable-command-map-cache-v1` implementation precompiles all 36
legal commands × two semantic destination maps and immutable profile bindings.
It caches no policy, label, model weight or input. The existing calibrated generation
key stays unchanged; a separate schema/key identifies and binds the implementation.
Loading requires explicit model/generation/implementation identities and reconstructs
all maps to reject tampering. Default serving APIs are unchanged.

The successful numerical path preserves the qualified reference operation order,
including its actual-CDF normalization, support, argmax and marginal checks. Per-call
map construction and profile/hash validation are amortized at compile/load; this is
not solely a map-lookup optimization and setup/binding are not free. Byte-backed map
views cannot become writeable. Old-source artifact compatibility is not promised.
One first-layer CDF rejection uses `ValueError` rather than the reference's
`NumericalDomainError` subclass: successful numerical law is equivalent, but exact
exception-subclass API identity is not claimed.

## Fixed literal parity and service-path result

Six tests passed: 3135 literal output rows spanning every command, batch sizes
1/36/1008 and three fixed temperature pairs were bitwise identical, as were 15
paired samples from supplied uniforms. Identity, serialization, tamper, immutability,
input and support-loss refusals passed. Five timed output pairs were also bitwise
identical. These are literal finite tests, not a proof over every floating input.

For the prespecified 1008-row literal batch, median process CPU was **0.035893459 s
reference vs 0.023949084 s cached**, ratio **0.667227**; the fixed <=0.8 performance
gate passed. Both full timing vectors, alternating order, setup and one warmup per
implementation remain in SUMMARY. This is the complete table/CDF/profile serving
API path, **not model inference or end-to-end generation latency**, and not a new
learning or quality gain. Earlier fair-NDU failures remain failures.

## Setup is measured, not free

The original one-off compile and serialization CPU observations were zero and are
retained verbatim. They are treated as censored/unresolved, **not true zero cost**;
the original derived compile break-even 0 is not a credible amortization claim.
Original load took 0.003997229 CPU s and recomputed 72 maps (in addition to the
72 maps compiled); the original result omitted this separate count field, not its
CPU. SUMMARY explicitly supplements that counter without rewriting the original.

A separately frozen, once-only accounting probe performed exactly 64 fresh-object
compiles, 64 serializations and 64 loads in one already loaded interpreter. It did
not retime serving or select a faster repeat. Mean instrumented CPU per instance:

| Stage | CPU seconds | Destination-map calls across 64 |
|---|---:|---:|
| Compile | 0.0014326292 | 4608 |
| Serialize | 0.0006216652 | 0 |
| Load/revalidate | 0.0028684700 | 4608 |

This is warm-interpreter fresh-object setup, not 64 cold process launches. Counting,
clock and list overhead are inside the timed stages. A further 128 identity dumps,
imports and all checks are included in the complete child. Using the historical
saved 1008-row service delta, compile-only and load-only estimates each amortize
within one such batch; this is not a simultaneous new paired performance claim.
Serialization and whichever compile/load path the caller uses must still be charged.

The original test/benchmark child cost **0.775283 CPU s**, 0.790147 wall s,
44928 KiB RSS under 5 CPU / 30 wall limits. The separate setup child cost
**0.577882 CPU s**, 0.588571 wall s, 27920 KiB RSS under 3 CPU / 20 wall limits.
Both used CPU 0, one numerical thread, existing shared lock, 512 MiB / 4 MiB,
full wait4 and no retry. Combined observed child CPU: **1.353165 s**. Historical
qualification, source/review and unknown supervisor tails remain additional, not zero.
No dataset, model restore, training, validation or TEST observation was accessed.

## Portable tests

Published sibling dependencies are the original qualified implementations in
`semantic-temperature`, `coupled-simplex-longdouble`, `coupled-law-gradient`,
`semantic-coupling`, `explicit-semantic-transport` and
`transport-aligned-training`, plus parent `control.py` and `utility.py`. Run:

```sh
PYTHONPATH=../semantic-temperature:../coupled-simplex-longdouble:../coupled-law-gradient:../explicit-semantic-transport:../semantic-coupling:../transport-aligned-training:.. python -B -m unittest -v test_cached
```
No production/default deployment or unrestricted scientific runner is added.
Fixed plans and complete aggregate receipts are retained alongside the code.
