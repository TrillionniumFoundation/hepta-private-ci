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

## Current closed environment and actual main-target pair

The preceding sections retain earlier increments, not the current source tuple.
PR #1454 continues the sealed owner from PR #1449. The last pre-spawn boundary
in `automation_effect_host_pon_process.rs` clears inherited and explicitly
staged environment variables and installs only `LC_ALL=C` and `TZ=UTC`.
All supported runtime inputs are the existing pinned arguments and exact
stdin. There is no environment pass-through, PATH-based binary fallback,
new permission, or HTTP-provider change. Existing deadlines, output limits,
pre-entry refusal and post-entry Unknown semantics are unchanged.

Sealing only the ELF does not prevent ambient dynamic-loader injection.
The existing native ELF test fixture now enumerates the actual environment;
a separate compiled shared-library constructor proves that the same sealed
ELF is affected by an unisolated `LD_PRELOAD` positive control. The actual
hardened exchange must consume its payload, expose exactly the closed
environment and leave no injected marker. Both tests run through the existing
native pair lanes with nonempty selectors. System loader/libraries, working
directory, inherited file descriptors and the host kernel remain trusted;
this change is not a sandbox or a complete execution-dependency attestation.

The current pair workflow pins Chain PR #253 head
`df717d7fb21a368cb5b4a240ef6221eaba977bc9`, main base
`9fedf7ecbbe07177069c030592b4e03dcffebb81`, and actual main merge
`45fbc027cd3d6e89a2792dca73e36a70eae42cfd`. Hepta also targets main.
Read each repository's exact tested head/tree/ordered merge parents and actual
results from that run. All original sealed submit/reconciliation/confirmation/
reorganization and growth tests remain required; prior pair success does not
qualify the new environment or this source tuple.

A local compiled C/Linux sealed-object injection/refusal experiment was run;
that is not compiled Rust or a real Chain/Hepta acceptance run. Current hosted
native and full blocking gates remain separate. Public PoN work qualification,
independent prospective generations, physical power loss, long-term data
availability, independently operated WAN capacity and production remain open.
