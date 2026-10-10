# CNS / Organ System / Organ / Driver

## Implemented profile and authority boundary

`organ_hierarchy.rs` implements the process-local, trusted-compiled, read-only
profile over the existing `OrganHostV1`. It is used by the live runtime status
consumer in `../../hepta-runtime/src/organs.rs`. It is not an arbitrary plugin
loader, a distributed scheduler, an effect authority, a model-selection owner,
or a replacement for the existing Codex execution spine.

The existing V2 compiled-body wire codec and `into_host` API remain unchanged.
`VerifiedCompiledBodyGraphV2::into_hierarchical_host` is the new admission path.
A structural tree is not the runtime dataflow graph: cross-system links and
local feedback remain in `OrganGraphsV1`, with its existing safety validation.
A motor or reflex loop must not acquire a synchronous dependency on the CNS.

## Four levels

| Level | Implementation responsibility | Excluded responsibility |
| --- | --- | --- |
| CNS | Select an immutable composition and address an admitted system capability. | No capability minting, arbitrary code loading or second domain database. |
| Organ System | Identify a coherent group of organs and expose their admitted routes. | No reassignment of canonical module owners or authoritative writers. |
| Organ | Retain stable capability, port, lifecycle and failure semantics. | No assumption that one module, process, device or driver equals one organ. |
| Driver | Implement an explicitly selected compiled handler under the existing owner. | An identity digest is not code attestation, a sandbox, or independent success evidence. |

`CnsHierarchyV1` holds CNS identity, generation, complete body-graph digest,
systems and driver bindings. `OrganSystemV1` defines primary organ membership.
`OrganDriverBindingV1` separates organ identity from driver-instance identity
and implementation digest. A host independently supplies `CompiledOrganDriverV1`
entries; supplied hierarchy metadata does not construct handlers.

Admission rejects duplicate systems, empty systems, missing/unknown/multiply
assigned organs, reused driver-instance IDs, missing drivers, incorrect
implementation bindings and mismatched handler/manifest identities. Every organ
in an admitted body belongs to exactly one primary system and one selected
handler instance. Shared implementation code is allowed, shared instance IDs
are not. Library modules are not fabricated as executable drivers.

## Snapshot identity and local dispatch

The hierarchy binds the digest of the complete canonical V2 body encoding,
not only `BodyGraphBindingV1.snapshot_digest`, which is source provenance.
System membership and driver selection are included in a separate
domain-separated hierarchy digest. Identities are length-prefixed; membership
is ordered canonically before hashing. Merely reordering declaration lists
therefore does not change a route; changing membership, driver implementation,
body topology, placement or generation does.

`CnsOrganHostV1::route` returns a `CnsRouteV1` containing CNS identity, generation,
hierarchy digest, source system/organ/driver, output port and all target paths.
`dispatch_once` compares the entire supplied route to the immutable admitted
route before calling the existing host. Edited and stale routes fail before
handler invocation. A route is not an authority token.

`CnsDeliveryV1` retains the original `OrganDeliveryV1` and adds the four-level
source and target identity. Original host bounds, readiness, partial-delivery
counts, quarantine and stop semantics remain in force. A failed dispatch never
falls back to directly calling the underlying state adapter.

Current bounds follow the existing graph (at most 128 organs and 1,024 runtime
links), with at most 32 nonempty systems. The existing 64 KiB message limit is
unchanged. Routes are precomputed once; dispatch has no central network RPC.

## Actual first consumer

The live status path is:

`hepta.runtime.cns` -> `system.cognition` / `runtime.status.ingress` ->
`system.homeostasis` / `runtime.status.adapter` -> the selected compiled status
driver -> the existing `RuntimeStateAdapter` observation.

This is one cross-system graph hop with two compiled organ instances. The
existing public status JSON remains unchanged. Busy, stopped, invalid-route and
failed hosts do not bypass hierarchy dispatch. It does not establish that all
forty module capabilities have been migrated or that a model/provider C1 is
complete. The host's compiled driver labels are not binary measurements.

## System decomposition for the forty canonical modules

The following design mapping covers the existing forty-module registry without
renaming packages or changing owners. It is a decomposition guide, not a second
module registry or an activation manifest. Canonical identity and writer facts
remain in `../../../docs/modules/MODULES.json` and the data-authority registry.
An organ may use modules from several systems through their existing contracts.
Only concrete selected organs, not every library listed here, appear in a
runtime `CnsHierarchyV1`.

| System identity | Canonical modules (primary design grouping) |
| --- | --- |
| `system.integrity` | `kernel.authority`, `kernel.operations`, `kernel.evidence`, `auth.authbus`, `secrets.heptabao` |
| `system.foundation` | `platform.types`, `platform.wire` |
| `system.homeostasis` | `runtime.supervisor`, `runtime.fleet`, `inference.control` |
| `system.cognition` | `objective.compiler`, `utility.ndu`, `control.runtime`, `runtime.agentd`, `runtime.codex`, `intelligence.control` |
| `system.memory` | `cognitive.types`, `cognitive.store`, `cognitive.read`, `memory.retrieval`, `memory.federation`, `knowledge.graph`, `compact.engine`, `prompt.registry`, `context.compiler` |
| `system.learning` | `learning.ledger`, `learning.operator`, `learning.eval`, `learning.artifacts`, `learning.plasticity`, `neuron.runtime`, `intuition.policy`, `prompt.optimizer` |
| `system.perception` | `browser.servo` |
| `system.communication` | `channel.matrix` |
| `system.human-interface` | `ui.control`, `ui.native` |
| `system.execution` | `inference.worker`, `automation.taskflow` |
| `system.evolution` | `control.engineering` |

The 24 reference organ roles in `../../../docs/cns/CNS_ARCHITECTURE.json` remain
separate from module IDs and concrete runtime instances. For example, the memory
organ can compose storage, retrieval and graph modules, while a browser driver
can support both observation and action organs. The existing reference catalog
must not be promoted to active drivers because it contains a module binding.
`kernel.evidence` remains qualification-plane evidence; this grouping does not
put qualification code on production sensory or control hot paths.

## Evolution and compatibility

Each admitted composition is immutable. `CnsOrganHostV1::replace_read_only_generation`
accepts a separately admitted, registered successor under the same CNS identity.
It requires the exact current generation and its immediate successor. Additions,
retirements, system membership and selected drivers change together with the
complete graph; the wrapper does not expose a mutable flat-host escape hatch.

Cutover reuses the existing host lifecycle implementation. Candidate validation
or startup failure leaves the predecessor and its routes unchanged. If stopping
the predecessor fails, candidate cleanup is attempted and its faults are returned;
the old identity remains visible with stopped or quarantined organs. Such a host
cannot dispatch through its retained routes. Only successful cutover publishes
the new routes, under the same exclusive mutable access as the host replacement.
Previously cached routes then fail before a handler runs.

This is a process-local read-only replacement, not a crash-durable transaction,
a data migration, or an autonomous policy selecting which organs should change.
It does not add a second lifecycle implementation or an authoritative store.

Before a future effectful or stateful profile is admitted, its owner must provide
final-use authorization, bounded I/O, trustworthy terminal observation, unknown
outcome reconciliation and persistent writer handoff. Replacing the graph must
not restore stale application data or revive deletions. Qualification-only
hardware roles, physical safety and future-window learning claims require their
own evidence and cannot be inferred from these read-only tests.

## Verification

Run the existing repository commands for both implementation and consumer:

```sh
cd codex-rs
cargo check --locked -p codex-hepta-control-plane -p codex-hepta-runtime --all-targets
just test --locked -p codex-hepta-control-plane -p codex-hepta-runtime
cargo clippy --locked -p codex-hepta-control-plane -p codex-hepta-runtime --all-targets -- -D warnings
cargo fmt --package codex-hepta-control-plane --package codex-hepta-runtime -- --check
```

`organ_hierarchy_tests.rs` exercises actual fixture handlers, cross-system fanout,
full delivery values, route edits, independent catalog/manifest rejection, graph
identity, declaration ordering, replacement identity and partial failure. It also
executes repeated live add/retire/driver-replacement cycles and checks wrong CNS,
stale/skipped generations, already-started candidates, stopped predecessors,
candidate startup/cleanup faults and predecessor shutdown faults.
`../../hepta-runtime/src/organs_tests.rs` verifies that the existing consumer
rejects altered routes without observing its state adapter, then succeeds with
the restored route. These tests are not a production effect or learning benchmark.
Exact source and synthetic merge checks run in the existing organ implementation
workflow. CI results, not this document, establish whether a revision passed.
