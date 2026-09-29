# knowledge.graph runtime delta closure — 2026-09-29

## Scope

This note records the repository-controlled runtime transition boundary added after the
2026-09-29 `knowledge.graph` review. It does not grant independent operator acceptance,
activation, promotion or release authority.

The durable product owner remains the existing cognitive SQLite database. Immutable
memory revisions and revision-scoped KG facts remain authoritative. A graph generation
is a deterministic projection over one exact source cut; it is not an independent fact
ledger.

## Selected transition path

For every generation after the baseline, `CognitiveStore::refresh_scope_projection_tx`
now performs all of the following inside the same `BEGIN IMMEDIATE` transaction:

1. observes the exact current source cut and reconstructs the canonical predecessor;
2. builds the canonical candidate generation;
3. builds `KnowledgeDependencyIndexV2` for the predecessor;
4. invokes `plan_generation_transition_v2` to derive the exact ordered storage delta and
   bounded impact closure;
5. requires the kernel to reapply that delta and reproduce the candidate generation
   digest before publication can continue;
6. validates predecessor-bound publication semantics;
7. persists the source-cut, semantic, compact-storage, transition and kernel-delta
   receipts; and
8. advances `kg_projection.generation` with compare-and-swap only after SQLite triggers
   prove those receipts exist and agree.

The kernel delta records node and edge removals/upserts, the directly affected node and
edge closure, the predecessor digest and the candidate digest. The receipt is immutable.
Deleting or rewriting it is rejected by SQLite.

## Durable storage model

Fresh generations continue to use `revision_facts_v1`. They do not copy a complete
`kg_nodes`/`kg_edges` snapshot for every generation. Historical generations are rebuilt
from immutable revision facts and generation trigger history. The kernel delta receipt is
an audit and recovery witness; it does not become a second source of factual truth.

The current-generation pointer has three fail-closed gates for post-migration writes:

- a canonical generation semantic receipt;
- an automatic transition/resource receipt; and
- for every non-baseline generation, a kernel-delta receipt bound to the predecessor and
  candidate generation digests.

A missing or mismatched gate aborts the enclosing transaction, including the cognitive
mutation that attempted to publish it.

## Physical resource contract

The transition receipt records exact previous/next trigger support counts, touched
canonical entity/relation counts and the measured trigger payload bytes. SQLite rejects a
single trigger revision larger than 4 MiB before publishing its compact-storage witness.
This durable boundary complements the `hepta-kg` limits for canonical input/generation
bytes, per-field bytes, JSON bytes/depth/elements, query-output bytes, deadlines,
cancellation, publication concurrency and digest-keyed query caches.

These limits are deterministic admission contracts, not a claim about observed target
host latency or RSS. Target-host qualification must still retain operation measurements,
DB/WAL bytes, process memory and CPU observations under a predeclared profile.

## Full-rebuild oracle and remaining compute-locality gate

The product transaction currently still constructs the complete canonical candidate from
the bounded current source cut. The kernel delta is therefore runtime-selected and
durably receipted, and its exact equivalence to that candidate is mandatory, but the
complete candidate remains the per-mutation oracle rather than only a periodic oracle.

Consequently, this change closes transition correctness, recovery identity and durable
observability. It does **not** yet claim asymptotically local source scanning or that the
full rebuild has been removed from the hot path. Promoting the complete rebuild to a
periodic-only audit requires target-host evidence showing that localized source-cut
maintenance is beneficial without weakening correction, final-support deletion,
anti-resurrection, crash recovery or publication-chain verification.

## Qualification and authority

Repository-controlled qualification must run independently for:

- the exact source head;
- the current `main` head; and
- the deterministic synthetic merge.

Formatting is a separate job and cannot prevent functional tests from running. Required
functional evidence includes `hepta-kg`, cognitive SQLite integration, child-process
crash/recovery, product Agentd retrieval, adversarial/property cases and physical resource
checks. Every receipt must bind the exact source SHA, tree, workflow definition,
lockfile/toolchain inputs and artifact digests.

The generated status model keeps implementation, testing, integration, evidence,
operator acceptance, activation and release as separate states. There is no single
completion percentage. Until an independently authorized identity signs and a separate
verifier accepts a current candidate manifest, operator acceptance remains false,
activation remains disabled and release remains ineligible.
