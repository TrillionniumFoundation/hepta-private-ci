# Persistent refractory release packets — research prototype

The original remaining-time bins reconstruct a uniform law after every step.
The phase-only exact oracle in #6096 identifies the resulting artificial early
release. `refractory_transport.py` now supplies a reusable immutable state that
retains absolute release-time support between calls instead of feeding projected
phase bins back into state.

Each packet carries a positive total probability mass and signed marked-content
totals, on a uniform interval or point. A fixed episode delay shifts an external
hit-time packet into its release law. `advance_to` clips that law exactly at the
query time and returns both remaining state and released support packets. The
caller must integrate each released support against its active evolution; putting
all released mass at the query endpoint would change the process. Read-only
`project_remaining` exists for comparisons and does not mutate the law.

`Fraction`/integer inputs make the stated geometric transport exact. This is a
reference representation, not a floating-point/autograd implementation. At most
4096 simultaneous input-plus-pending packets and 128 content channels are
admitted. Overflow fails before any state update. Packet count bounds do not
bound rational bit complexity, total retained receipts or total process memory.
IDs are local pending-set identities, not a durable replay/owner authorization
ledger. Supplying the same external hit influx twice would count it twice.

Reproduce from the repository root:

```sh
python -m unittest qualification.hcsn_boundary_audit.test_refractory_transport qualification.hcsn_boundary_audit.test_phase_delay_oracle -v
python -m qualification.hcsn_boundary_audit.probe_refractory_transport /tmp/refractory-result.json
```

The retained local execution passes **8 new + 4 existing tests** without skips.
For all eight original source cells and 2/4/8/16/32 alternating irregular
substeps (40 combinations), persistent-state projection has exact zero TV to
direct geometry at total time 0.02. The original equally spaced per-step-bin
baseline retains TV maxima 0.32 through approximately 0.43505. These schedules
are explicitly different; the baseline numbers reproduce the historical
equal-step control, not an equal-schedule performance comparison. Tests also
cover interval influx, zero-delay/point releases, release-time moments, signed
content, projection edge atoms, clock/shape checks and overflow.

The external hit law is supplied rather than solved. Uniform hit packets are a
separate upstream approximation if the true first-hit density is not uniform.
There is no active diffusion, renewal feedback loop, trained-posterior filtering,
checkpoint migration or physical-parameter differentiation here. The original
Torch operator and the 14,336 failed continuation-value gates are unchanged.
The new stdlib-only exact-head workflow does not qualify a full HCSN candidate.
All numerical/science/adoption gates remain **HOLD_NO_GO**.

Original local logs and source hashes are under
`evidence/age-preserving-transport-20261112/`. Tests and the probe preceded
`just fmt`; source bytes remained identical afterward. Formatting reports no
owning formatter for these qualification paths. This small process timing is
not an end-to-end cost, hardware/energy or throughput claim.
