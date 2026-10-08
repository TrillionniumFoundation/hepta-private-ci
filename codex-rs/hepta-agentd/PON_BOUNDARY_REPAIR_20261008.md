# PoN boundary repair, 2026-10-08

Source base: f4165797e3a96a0a9d2b566e84c48880d2dfff29 (PR1437).
Inherited bounded exchange: 32740b3662dcffdd905a1095d3ee7f402d9def13 (PR1434).

The existing Agentd host now uses the bounded asynchronous pipe exchange with
one original deadline and equal stdout/stderr bounds. Started-but-uncertain
work remains Unknown. Original exact effect/payload binding and signed
depth/work confirmation policy remain intact. Native observation parsing now
recomputes height depth, checks active-tip identity and requires positive
work distance for a distinct active ancestor. Oversized bytes reject before
adapter-owned copies. Tests cover full/blocked input, both output limits,
incomplete JSON, nonzero exit, inherited output pipes and contradictory
observation fields. Historical tests are adapted to the current v3 shape;
historical success is not inherited.

Validation must run on this delivered source: just fmt; just test -p
codex-hepta-agentd; just test -p codex-hepta-agent-protocol; scoped Clippy and
the ordinary architecture/required CI. Source materialization is not a test.

Remaining obligations are explicit: binary hash-to-execution object binding,
independently current artifact/withdrawal/selection/final-use checks, real
installation and three-generation consumer benefit. Chain owner_generation
is not a Hepta final-use generation and cannot be compared by casting them.
No second journal, supervisor, trainer, or registry is introduced. Model
parameter adoption does not authorize neuron code/topology replacement;
neither authorizes a consensus/verifier upgrade. Such upgrades require their
existing distinct authorities and fresh explicit protocol contexts.

Physical power loss, independent WAN operators, sustained public capacity,
and model efficacy are not claimed by these local pipe fixtures. No release,
production, branch protection or deployment setting is changed.

## Latest exact-pair convergence (no second authority)

The stacked Hepta integration source is PR #1444 at
`a36dfbb2dd09fec95751522b6e4fc96598b18f14`. Its installed PoN
process exchange, exact v3 observation parser, sealed immutable ELF
execution object and same-candidate pipe/height/work/effect tests are retained
unchanged. PR #1445 was developed separately against the older PR #1437;
its bounded-process fixes cannot replace the sealed execution owner. Both
sides were inspected; no historical or parallel PR pass is inherited.

The paired CI pins Chain PR #248 `560d44ac28fee7b073d1740e372839ab52f057b6` and the
matching GitHub prospective merge `6731581b65a6300e5c2bb73566d582227ee932b7` against its
base `bf2f6c72cb4881545f03b6ebe55a5e5e6a7af988`, in both x64/ARM64 and source/merge
lanes. That Chain PR fixes the *historical cost-report checker* after new
hostile/honest-arrival overlap screening without editing evidence or relaxing
current work admission. The pair still executes the actual Chain binary,
native growth-readback selectors, Agentd sealed submit/reconcile/reorg and
explicit negative process tests. Run results MUST be read from this final
Hepta head and its prospective merge, not PR #1444's earlier successful pair.

This is an exact-source integration increment only: no public-network hardness,
new native storage capacity activation, genuine third-party model training/
adoption, independently operated WAN campaign, physical power-loss, public
service SLA, final-use override, production consensus, or release is accepted.


## Seven-workstream convergence onto Chain #250

The current stacked PoN pair runner is re-pinned to Chain PR #250 head
`1bd94e331a238a94904e8c82749781a7173f4317`, its exact base
`560d44ac28fee7b073d1740e372839ab52f057b6`, and the observed
prospective merge `dc67f953356d514ac51df9ce477692b5d7bfeb37`.
The previous Chain #248 tuple above remains historical; it is not a
claim about the new source. Chain #250 adds a real non-tip packet-status
height/work verification and heavier-branch reorganization test on the
existing strict work-cost evidence/arrival screening owner. No new chain
work rule or model authorization is introduced. x64/ARM64 and exact-head/
base-merge paired CI must execute again on this exact combination.

The previous #248 source's native sustained-service test reported a failed
honest state equality assertion in one hosted run. Neither the new
packet-status test nor a passing paired binary smoke erases that failure.
Subsequent work must diagnose the actual full-state discrepancy and rerun
the unweakened simultaneous honest/hostile arrival campaign. Independent
operators, future model efficacy, production, and release remain false.
