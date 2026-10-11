# W0 source preparation and seven-lane handoff

Status: `pre_entry_source_preparation`. This is a candidate work plan, not a
reviewed lane envelope, canonical source receipt, W0/I0/I1 pass, independent
acceptance, selected body generation, activation, merge or release decision.
The canonical registries and their gates are unchanged.

## 1. Exact preparation baseline

The private preparation branch starts from commit
`e9b14bbbbd611ebee2e7f5c5a4238d378882ea0f`, tree
`e05fc9adb1721214f20c37efbb269112333be012`. Its ancestry includes the unmerged
PR #464 candidate and an exact-byte replay of the earlier product-closure
candidates from draft PRs #465–#468. Neither this ancestry nor local test
success selects that candidate as the repository's canonical source.

The same tree is published for review as commit
`2bdb377497eb924f592a8d37b378f03c2f2f7078` on
`codex/hepta-w0-review-base-20260908`, with the single parent
`5b3ddb70e9f69efb1bdff9a9e7b0e7f16e07c470`. Local and published preparation
commits have different identities and ancestry; only their tree bytes are
equal. Published lane candidates use the published base, not the local SHA.

At every handoff, obtain a fresh `w0_snapshot.py snapshot` observation for the
exact committed candidate and its named ancestor. Supply full commit IDs, not
branch names. Keep the resulting observation outside the source tree it
describes; committing a snapshot of its own HEAD would create a circular
identity. A subsequent `check` must recompute from Git and reject drift.
The proposal records all seven lanes and all 40 modules, guide/dossier
identities, document-system bytes, protocol/contracts, and path ownership.
It does not manufacture a principal, reviewed lease, TTL, receipt or test run.

Formal W0 entry still needs the externally reviewed source receipt, branch
purpose, frozen contract identity, current bounded lane envelopes and required
independent decisions. A cached proposal cannot satisfy those obligations.

## 2. Lane partition and first private slices

Counts and owners are projections of `docs/readiness/READINESS.json`.
Additional candidate roots do not widen canonical ownership. Shared contracts,
Cargo manifests/lockfiles and registry changes require a single integrator and
the applicable co-owner review, not concurrent lane edits.

| Lane | Modules | Owner / deputy | First bounded candidate in this branch | Verification boundary |
|---|---:|---|---|---|
| A — foundation | 7 | kernel-contracts / architecture | Wire decoding verifies the borrowed payload before copying it; exhaustive frame boundary tests | Every truncation offset, malformed lengths/IDs, maximum payload and corruption; no wire schema change |
| B — runtime | 11 | runtime-control / security-authority | Bind the existing request deadline into inference-plan and Codex-adapter request digests | Same request remains deterministic; changing only the deadline changes the digest; no provider invocation |
| C — memory | 9 | cognitive-platform / durability-kernel | Reject an explicitly present same-record tombstone-to-live ancestry in snapshot reads | Valid live/tombstone histories, reordered records, truncated ancestry and cross-record/fork non-inference |
| D — objective/value | 3 | intelligence-platform / learning-platform | Exhaustive independent truth-table comparison of the existing Horn feasibility solver | 4,096 three-action cases; witness truth, inclusion-minimal conflicts, permutation stability and oracle-call bound |
| E — learning | 4 | learning-platform / qualification-plane | Enforce the pinned encoded length before artifact/snapshot allocation and hashing | Exact lengths, global ceilings, short/oversized input, lock release and unchanged digest verification |
| F — adaptive policy | 5 | learning-platform / intelligence-platform | Freeze the body identity across successor neural ticks and reopen without changing encoding | Same-body continuation, body drift rejection, replay and no current-run mutation |
| G — engineering control | 1 | developer-productivity / architecture | Read-only W0 snapshot/check CLI and malformed-input/drift tests | Seven-lane/40-module coverage, exact source/document identity, path conflicts and always-negative authority |

These are bounded implementation/test slices, not completion claims for the
40 modules. In particular D's test expansion does not add a V1 source-envelope
compiler adapter or prove NDU efficacy. E's read-budget work does not implement
dataset freezing, independent evaluation, selection or live artifact reload.
B's digest repair changes derived request identity: persisted receipts must not
be silently relabelled compatible; consumers need exact-candidate review.

The module membership remains:

| Lane | Canonical module IDs |
|---|---|
| A | `platform.types`, `platform.wire`, `kernel.authority`, `kernel.operations`, `kernel.evidence`, `auth.authbus`, `secrets.heptabao` |
| B | `runtime.supervisor`, `runtime.fleet`, `runtime.agentd`, `runtime.codex`, `inference.control`, `inference.worker`, `automation.taskflow`, `channel.matrix`, `browser.servo`, `ui.control`, `ui.native` |
| C | `cognitive.types`, `cognitive.store`, `cognitive.read`, `memory.retrieval`, `memory.federation`, `knowledge.graph`, `compact.engine`, `prompt.registry`, `context.compiler` |
| D | `objective.compiler`, `utility.ndu`, `control.runtime` |
| E | `learning.ledger`, `learning.operator`, `learning.eval`, `learning.artifacts` |
| F | `neuron.runtime`, `intuition.policy`, `prompt.optimizer`, `learning.plasticity`, `intelligence.control` |
| G | `control.engineering` |

## 3. Dependency-aware parallel delivery

Seven lanes are ownership workstreams, not permission to ignore predecessors.
A supplies the frozen contract snapshot to B/C/G. D consumes A and C; E consumes
A/C/D; F consumes B/C/D/E. Contract-first private preparation may overlap;
integration proceeds only when each named predecessor's native port and
required evidence are present. `control.runtime` belongs to D, not B.

1. **W0 preparation:** exact source/document freeze, scope/ownership checks,
   fixtures, rollback predecessor, authority-negative checks and reviewed
   handoff. Do not infer integration from source preparation.
2. **W1 stores/runtime:** A/B/C integrate bounded ports, single-writer stores,
   migrations, revocation, recovery, organ admission and deterministic fallback.
   G supports source observations without claiming a W1 capability checkpoint;
   its governed candidate pipeline remains W5 work.
3. **W2 objective/value:** D joins coherent C reads and runtime composition;
   implement the explicit V1 source-to-objective mapping and deterministic NDU
   under separately reviewed contracts. Never weaken constraints to raise value.
4. **W3 learning evidence:** E integrates durable decisions/outcomes, complete
   action probabilities, eligible dataset freezing, bounded training and
   immutable artifact publication. F produces shadow-only candidates.
5. **W4 future evaluation/reload:** independently evaluated and selected
   artifacts load into a new process generation and demonstrate changed
   behavior, retention and rollback under current revocations.
6. **W5 governed code / W6 embodiment:** G's candidate pipeline and authorized
   external adapters precede independently qualified structural change. Real
   sensors, actuators, timing and emergency controls require physical evidence.

The product closure target remains the C1 chain in
`qualification/module-execution-dossiers/C1_EXECUTION.md`: real request,
immutable objective, coherent reads, complete candidate/assignment logging,
independent outcome, ledger fsync/reopen, eligible dataset, bounded trainer,
frozen evaluation, immutable artifact, independent selection, new-process
behavior change and revocation-aware rollback. Library fixtures do not prove
that chain, future efficacy, AGI or autonomous self-evolution.

## 4. Per-lane handoff and stop conditions

Each reviewed lane envelope must bind the exact source/tree and ordered
parents; source purpose; guide/dossier/contract identities; canonical owner and
deputy; exclusive paths and shared leases; native producer/consumer mapping;
state/transaction/error model; hard resource bounds; fixtures and fault cases;
rollback predecessor; test commands and actual observations; reviewer
identity/decision; expiry; and every outstanding gate. Use the canonical
dossier's eighteen receipt fields rather than replacing them with this table.

The first candidate tests run through the repository's `just test` recipe for
the affected packages, plus G's Python tests. Run strict scoped lint and the
repository-prescribed final fix/format sequence. Exact-head and synthetic-merge
CI, full-workspace checks, Bazel lock verification and independent review remain
separate observations; never invent them from a local package run.

Stop the affected handoff on source/contract drift, competing writers,
permission or ownership blockers, positive authority changes, unbounded work,
test/evidence disagreement, stale/revoked context or incompatible rollback.
The candidate may be prepared and reviewed without self-issuing acceptance.
No lane may rewrite canonical gates or native binding pins merely to turn CI
green. An access or infrastructure failure stays an explicit blocker.

External-system expansion means independently enrolled and authorized adapters,
not contagion: no implicit Debian host enrollment, root package changes,
credential transfer, propagated grants or inherited acceptance.

## 5. Published review stages and observed checks

Each lane is a separate draft PR against the same review base. None is marked
accepted or merged by this handoff. The assembled candidate is an observation
target, not a substitute for reviewing these bounded changes.

| Lane | Draft review | Exact lane head |
|---|---|---|
| A | [#472](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/472) | `cd148fc975a3d6b978a333d9424cff1c75a0b05c` |
| B | [#471](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/471) | `bfc72a48422a876691f95411b9bcdabbaaca7b43` |
| C | [#473](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/473) | `8ebee5e3ef81b546eca65b2f6b5e6321e595599a` |
| D | [#475](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/475) | `b11486441ec23c41c53d03772df492086410b7cc` |
| E | [#474](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/474) | `fd09179cf5f34dc30b3c96b8910d2ab71e62e99c` |
| F | [#476](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/476) | `aa4696290f9a0efdd90587289651a24f287b0f1c` |
| G | [#469](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/469) | `3704012db9ca4e029f7c5bda1fc04a28f0c5524f` |

Local observations from the combined preparation worktree, before final
fix/format (as required by AGENTS.md):

| Check | Observation | Limit |
|---|---|---|
| Foundation package group | 236 tests passed | Separate run; overlaps wire tests below |
| Nine-package lane group | 232 tests passed | Includes the 4,096-case Horn oracle and 16,384-record memory boundary |
| Runtime/gateway group | 16 tests passed | Initial E0463 build-artifact failures cleared after a scoped four-package cache rebuild |
| Engineering-control discovery | 69 tests passed | Includes 14 final W0 tests; no independent acceptance |
| Discovery CLI subprocess suite | 4 tests passed | Disposable explicitly scoped rootfs only, not a real Debian enrollment |
| Strict all-target Clippy | Passed on 11 relevant packages | Not a full-workspace build |
| Final `just fix` / `just fmt` | Passed | Tests were not rerun after these final steps |
| Development docs / readiness validators | Passed | 40 module guides, 117 canonical paths, seven lanes; documentation only |
| Implementation native-binding check | **Blocked: re-review required** | Inherited `codex-rs/hepta-learning-artifacts/src/lib.rs` differs from its canonical observation pin |
| Bazel lock verification | **Blocked** | Provided environment's archive-ownership failure; no extractor/permission workaround or lock pin rewrite |

No exact-head or synthetic-merge CI result is inferred from these local runs.
At the initial observation, G's readiness workflow had failed while other runs
were still running or passed. Query each published SHA again before handoff;
this text is not a live CI status or an expiring authorization.

Remaining formal W0 obligations are the exact-source receipt and branch-purpose
review, contract/native-binding re-review, current independently reviewed lane
envelopes and shared-root leases, applicable independent decisions, and current
required CI. The documentation validator observed zero externally attested
leases. Do not replace any of these with the proposer or a second model prompt.
