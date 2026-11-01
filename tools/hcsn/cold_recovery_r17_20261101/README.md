# R17 cold process and pending-action recovery

This is a bounded engineering qualification of the finite synthetic R16
four-address research owner. It adds a SQLite authority that commits the owned
memory, query cursor, pending action, action response, charges and effect IDs
atomically. Each replacement interpreter rebuilds the immutable model and owner
from JSON payloads and starts with empty transition and event caches.

The owner itself is a deterministic, read-only simulator. READ and REFRESH
retries reproduce the same keyed token. This is not an exactly-once guarantee
for a stateful external RPC or production Rust owner.

## Reproduce

Run from the repository root with the inherited R15/R16 dependencies present.
Use a new directory each time. `SOURCE_MANIFEST_V2.json` is the complete imported
project-source and cell-protocol freeze; the original v1 manifest and source
snapshots remain as a record of the initial dependency-coverage gap.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.cold_recovery_r17_20261101.campaign \
  --manifest tools/hcsn/cold_recovery_r17_20261101/SOURCE_MANIFEST_V2.json \
  --output /tmp/hcsn-r17-new-run
python -m tools.hcsn.cold_recovery_r17_20261101.audit \
  /tmp/hcsn-r17-new-run --output /tmp/hcsn-r17-new-audit.json
```

All state comparisons are exact JSON values, including checkpoint hashes,
actions, observations, fees, final memory and effect IDs. The uninterrupted new
state machine also has to match the complete query records of frozen R16
`execute`; preserving only reward is insufficient.

## Boundaries

Only one frozen fitted HX model (fit 151101), two deterministic fresh owner
worlds (IID and OOD), two representations (full and event-anchored), and three
policy/pattern settings are tested. Process-death fault locations cover WAIT,
READ and REFRESH before/after durable response and effect application plus a
value-policy query boundary. These are engineering cases, not 76 independent
statistical trials or evidence of core quality gain.

SQLite is the single local durable authority with FULL synchronous commits and
stale-sequence checks. Tests use real SIGKILL around committed transitions.
They do not exercise power failure, kernel reboot, concurrent writers,
distributed fencing, hostile storage re-signing, or a production transport.
Numeric CPU seconds are not joules. Production activation remains false.

Complete raw SQLite/log/snapshot evidence is preserved as 19 archive parts.
See [delivery_small/README.md](delivery_small/README.md) for reconstruction and verification,
and [delivery_small/MANIFEST.json](delivery_small/MANIFEST.json) for exact identities. After
extraction, audit `recovered-evidence/results/run02` using this study’s auditor.
