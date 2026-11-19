# Actual independent sparse warm-1 execution

Hosted run [44466138035](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44466138035),
job 135364262211, artifact 14501927547, source head
`2ae4e8639b7529ac0ad7288d834c8ceecca1915d` executed the new warm-1 identity
once. No new dense solve or full-roster candidate was executed.

The exact 35,819-byte downloaded ZIP is retained, SHA-256
`8f6a75afafeedaa5cfe6ad2b8b80af6b7d2b54f102f75d406ac1d92eb4b36629`.
All textual originals are copied without alteration. The complete
560,358-byte sparse capsule is inside the ZIP, SHA-256
`248cfc56d575b15d4a8340267e8b668fd0b6dc94be71b61e2b0cec8b913981b1`.

| Result | Actual value |
| --- | ---: |
| Complete coordinates compared | 69,728 |
| Pending packets | 9 |
| Bitwise differences | 1,291 |
| Maximum absolute coordinate difference | 9.08995101411847e-16 |
| Maximum symmetric relative difference | 5.5018733734279256e-14 |
| Generator coordinates, bitwise identical | 65,544 / 65,544 |
| Output coordinates, bitwise identical | 264 / 264 |
| Independently summed channel balance residual, maximum | 4.173360553758618e-15 |

The differences comprise 1,269 active-state entries, two packet coefficients,
and five entries each in mass, discounted hit, occupation and upper state.
The original bitwise gate remains **RED**. All comparisons satisfy the recorded
descriptive numerical tolerance; that tolerance does not replace the old gate.

Two sparse actions had orders 258/259, nonzero counts 767/1,025 and summed wall
time 0.172250149 seconds. The complete limited child took 1.196541021 seconds,
with 116,212 KiB peak RSS; that time includes imports and 0.234044572 seconds
of coordinate comparison. It is not a controlled speed comparison with the
archived dense child, which omitted this new comparison phase. The complete
serialized state still occupies 560,358 bytes, including its packet generator.

The stdlib-only `review_actual.py` reproduces every comparison, authentic-input
channel balances, manifest checks, exact runtime identity and recorded static
resource checks. It performs zero dynamic steps and imports no numerical
library. Counters other than the recorded action list remain producer/source
claims rather than independently instrumented events. The 30-second freshness
check is enforced by runner/child source; its exact child-check timestamp is
not retained in the artifact for an independent age reconstruction.

This result covers only 0 to 0.001. It provides no training-gradient,
long-rollout, full-roster, large-grid or production-adoption qualification.
