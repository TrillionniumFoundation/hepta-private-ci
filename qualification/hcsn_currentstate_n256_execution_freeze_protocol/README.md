# N256 execution-freeze protocol — HOLD

This package freezes a fail-closed protocol for a later N256 uniformization
execution. It performs no host selection, hardware probe, cgroup read,
allocation, calendar reservation, provider call, numerical solve, review, or
execution-key allocation.

The protocol requires the future runtime profile, host snapshot, ancestor
cgroup snapshot, allocation, and calendar originals to share one explicit
capture-session identity and host alias. Each capture must precede the frozen
execution interval. The originals may have distinct capture timestamps; the
shared session and host prevent an unrelated or stale snapshot from being
mixed into the execution freeze. The exact #6345 child request and frozen
provider source are also bound.

Provider-author identity and independent reviewer identity, custody, and review
artifact remain separately required. Provider self-review and conflated
identity/custody fail closed. This protocol does not create or certify any of
those originals.

## Current result

- future originals supplied: **0/10**
- resource bundle admitted: **false**
- provider admitted: **false**
- numerical execution allowed: **false**
- large-grid qualification: **false**
- production adoption: **false**
- historical RED and UNKNOWN preserved: **true**
- provider/dynamic/expm/oracle/model/Torch/optimizer/training calls: **0**

Synthetic unit fixtures test only the validator shape. They are not evidence,
do not allocate a host, and cannot be substituted for external originals.
