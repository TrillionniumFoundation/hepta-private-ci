# Bounded admission and memory source-observation migration

This change separates historical navigation provenance from current observed
content for five maps. It reuses v3 `candidate_or_exact_observation_v1` plus
`mappingSourceIdentityMode=exact_blob`; it changes no verifier, source code,
workflow, ownership, executable claim, acceptance gate or authority.

## Immutable inputs and retained history

The pre-migration repository is commit
`6bed10227078bf753c924ae94f02427efe13a1c6`, tree
`5b3610c4891a454c18be5a1e6a7f79269c1d2cb1`. Original maps, including the complete
previous observations and their explanatory text, remain accessible at that
commit under `docs/modules/<module>/IMPLEMENTATION_MAP.json`. Their exact Git
blob identities are:

| Module | Original map blob | New observation | Complete closure paths |
|---|---|---|---:|
| runtime.supervisor | `ffe7a699b257a42b4e012f98e8efc0188d004792` | c15884e5 | 14 |
| runtime.agentd | `240ff72581139d36e40309539f4467edb6aa0585` | c15884e5 | 21 |
| kernel.operations | `e6164ec1593c34b75b602a9cf7c68093f7b90ae0` | f2661efa | 31 |
| memory.retrieval | `0097b0bc79aabdd1e553e79a9fec627922eca830` | f2661efa | 43 |
| cognitive.store | `519e222d0f68187d74fbdf7571cc9590171849ec` | f2661efa | 21 |

Observation identities are published source commits:

- `c15884e527746ad633728c442415ab73af7188b6`, tree
  `2e17d727fdd04e5609f897b875778511d15f3933`.
- `f2661efafcd4bef72ec22c37ed4947f19ca1e1de`, tree
  `645b9fa2c684c9bb5dd01a3b271aa994620c55ab`.

Every closure path was checked unchanged between its observation and the
pre-migration candidate. Original `sourceBase` commit/tree pairs and their
ancestor/tree requirements are retained exactly. The old supervisor convergence
interpretation and operations/retrieval observations remain historical records
in the original map blobs above; they are not rewritten as new qualification.
Agentd's `currentSourceEvidence` at `cbb3cee0` is retained byte-for-byte as JSON
content and is historical lifecycle evidence, not the new current observation.
Cognitive.store retains `sourceBaseSemantics=exact_non_projection_source_snapshot`
for its original historical snapshot. All status, completion, composition,
operation semantics and evidence/authority flags are unchanged, including false
production implementation, product execution, independent acceptance, activation
and release. No positive executable claim is migrated.

## Scope and closure

Only exact navigation fields change: observation identity/path inventory,
operation blobs, source objects, and kernel.operations' existing path/blob
manifest values. Source objects and observation paths cover the union of existing
resolved roots, operations, tests, delegates, callers, guides, explicit legacy
witnesses, manifest entries, prior observed paths, historical evidence paths and
both Rust workspace build-input files. No existing witness is removed.

The operations closure additionally retains explicit local outbox/migration,
Agentd configuration/state and automation ledger paths beyond the earlier
24-path supplement. The new operations manifest pins both
`local_lease_outbox.rs` and `production_writer.rs`; retrieval observes
`cognitive_intelligence_writer.rs`; cognitive.store observes its production writer.
The older c158 admission supplement remains unchanged and limited to that source.

## Verification and limits

The reviewed dictionaries were validated as one complete selection before any
map write. Five damaged-plan cases (omitted explicit closure, missing evidence,
wrong original tree, changed execution claim, and unrelated map selection)
rejected before the write callback. Exact original-field preservation and all
unrelated map bytes were checked. The existing map, source-identity and CI-identity
regression suites passed 131 tests after applying the maps. No Rust build ran.

After committing the candidate, the existing selected migrator returned zero
changes twice with every write prohibited. Thirty actual-map negative probes
rejected invalid historical/observed trees, missing observations/roots/evidence
and omitted workspace locks. Committed map bytes matched the reviewed dictionaries;
all original non-navigation fields and unrelated map blobs remained identical.
The real global verifier accepted these five source observations while retaining
the failures listed below. Lane B now reaches automation.taskflow's genuine
nonancestor failure instead of stopping at the migrated supervisor observation.

Source navigation does not establish executable qualification. The separately
verified 2357 memory test/lint receipts remain scoped historical results; this
change neither reissues them nor expands their coverage. See
[the existing exact-head verification](../memory-transaction-api-20261002/HOSTED_2357_VERIFICATION.md).

Broader source drift remains in platform.types, kernel.authority,
inference.worker, intelligence.control, memory.federation, knowledge.graph,
learning.operator and learning.plasticity. Genuine nonancestor failures remain in
objective.compiler, utility.ndu, cognitive.read, learning.ledger,
learning.artifacts and automation.taskflow; control.engineering's missing source
object remains a failure. Their maps are untouched. Global acceptance, current-main
merge acceptance, target-host qualification, activation and release remain false.
