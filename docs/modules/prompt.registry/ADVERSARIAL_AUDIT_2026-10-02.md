# prompt.registry source-cut audit, 2026-10-02

## Scope and exact baseline

The independently re-read candidate is PR #1301, branch
`audit/prompt-registry-20261001`, commit
`9a66aa507117015e5d11083bfd8bfc29cb3ee641`, tree
`f6d802943dd12c5b1b1184dce72d22957c93428b`. The PR remains draft. Its previously
published guide, both dated audit records, implementation map and detailed
execution dossier were checked against this exact source, including all 15 mapped
operations and the optimizer/intelligence/Agentd consumer boundaries. Local
repair and validation below are a new candidate, not retroactive qualification
of that baseline or of a prospective merge.

## New reproducible finding and repair

The optimizer dropped enumeration's source registry cut when it constructed a
selected portfolio. Its public `candidate_set_digest` carried only realization
list bytes, and exercise created a new current snapshot without comparing it
with the original. An empty result did not consult the registry at all. Thus a
registry revision advance returned `NoIntervention` for a prior empty selection
or `Exercise` for a prior nonempty selection whose chosen binding still existed.
This was reproduced with real durable registry admission, signed learning
pricing, canonical selection, and an unrelated draft insertion; both regressions
failed before the repair. The failure is source-revision/provenance loss, not an
assertion that a heuristic selector proves global optimality.

The optimizer dossier §3 requires portfolio and exercise receipts to bind source
registry revisions. The repair retains one private 32-byte enumeration snapshot
digest, includes it in the process seal, and compares the exact current cut before
both decision branches. Changed cuts return `RejectStale`; callers must enumerate,
price and select again. Existing model/time/lifecycle checks remain. Registry
mutation authority, ownership and storage schema are unchanged.

### Receipt compatibility and recovery

Canonical portfolio digest encoding is now
`hepta.prompt-optimizer.portfolio-receipt.v2`. Its `candidate_set_digest` binds the
complete enumeration receipt, including registry snapshot/revision, objective,
model, grammar and omitted count. The private selection seal uses
`hepta.prompt-optimizer.verified-portfolio.v2`. Equal candidate lists from distinct
source cuts therefore produce distinct portfolio and downstream exercise receipt
identities. Keeping the native V1 Rust type names and field layout does not make
this digest-semantic change backward compatible.

The legacy V1 receipt domain remains historical; no migration rehashes or relabels
old values. The new validator rejects a legacy list-only receipt even if a test
internally remints the private seal. Production has no serialized constructor for
`SelectedPromptPortfolioV1` or its private seal. Intelligence consumes the sealed
object and binds its receipt transitively; no downstream production comparison
expects the former bare candidate-list digest. Agentd persists attachment,
dispatch and terminal identities, not reconstructable canonical portfolios.
Those existing journal records are not rewritten or upgraded here. Their separate
physical-send currentness/revocation gap remains open.

The exact snapshot is a semantic source cut, not a filesystem-instance identity
or proof that an independently restored copy is current. An unchanged anchored
reopen preserves a valid decision; a changed cut stays rejected after reopen.
Independent witness authentication/currentness is still the host's obligation.

## Adversarial coverage

- Empty and nonempty selections reject an unrelated registry revision advance
- Unchanged anchored reopen and repeated exercise preserve the complete decision
- Changed anchored reopen cannot restore an old selection's validity
- A different registry cut with identical selected bindings is rejected
- Equal candidate/pricing bytes from different enumeration sources have distinct
  public portfolio receipt identities
- Legacy V1 list-only receipts and rehashed candidate-source tampering fail closed
- Existing native tests cover input bounds/canonical codecs, immutable payload
  ownership, exact model profiles, terminal lifecycle/supersession, grant replay,
  poison/reopen behavior, selected extent corruption, migration and recovery cuts
- Intelligence prompt tests exercise sealed consumer compilation, declared token
  limits, 16-MiB serialization bounds, exact selected role and bounded KMP search;
  a source change blocks both fresh compilation and previously prepared delivery

## Execution evidence and limitations

Validation commands use repository `just test`, locked offline dependencies, a
separate target directory, two build jobs, debug information disabled and no
incremental build. The two new source-drift regressions failed before the repair
(`NoIntervention` / `Exercise` instead of `RejectStale`). The final post-fix/format
package command executed 241 tests: 89 registry, 57 optimizer, 93 intelligence
library and two intelligence integration tests; all passed, zero skipped. Six
new regression identities cover source-cut/provenance loss and the direct
intelligence compiler/prepared-delivery boundary. The first repaired 143-test run
and intermediate 239-library-test run are superseded by that complete small-package
execution, not represented as additional independent coverage.

The earlier intelligence prompt filter executed 19 tests successfully with 73
unrelated tests filtered out, including all eight bounds/search regressions left
unexecuted in the previous audit. The final full package run executes those
formerly filtered tests too. All-target check passes for all three packages.
Scoped `just fix`, final `just fmt` and format-check pass; strict registry and
optimizer Clippy with tests and `-D warnings` passes. Combined intelligence strict
lint is blocked in unchanged `hepta-context-compiler/src/v2.rs`: the empty line
after the doc comment at 99 and `observe_delivery`'s argument count at 1995.
No combined strict-lint pass or unrelated dependency repair is claimed.

Development ownership/docs, module docs, implementation maps, caller scanning,
execution dossiers and detailed-design verification pass. Only the two changed
prompt dossier digest rows are refreshed; authority/activation flags and unrelated
historical sources are preserved. These are local working-candidate checks;
publication still requires exact committed-source and independent review evidence.
They do not establish full Agentd/V8 execution, a deterministic synthetic-merge
run, independent semantic acceptance or deployed behavior.

The exact old-head architecture run
[36871779319](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36871779319)
failed source-head job 110401689495 at the `runtime_executable` selector with zero
tests against a minimum of one. The source file/tests are unlinked from Agentd's
module tree. The base-merge job 110401689731 skipped every native step 16–22;
its successful wrapper is not independent native merge execution. This audit does
not lower the threshold, enable an orphan only to produce test counts, or inherit
that wrapper success. Live runtime-module composition belongs to the coordinated
runtime owner repair.

## Completion by boundary

| Boundary | Verified scope | Remaining work |
| --- | --- | --- |
| Native registry owner | Bounded Unix durable owner; versioned codecs; immutable payloads; terminal lifecycle; anchored exact-cut API | Retention/compaction; representative scale/latency qualification |
| Source provenance and consumers | Sealed enumeration/pricing/selection, exact source-cut invalidation, compiler/staging source contracts | Full final-candidate Agentd and synthetic-merge execution |
| Governed mutation ingress | Final-use-bound owner APIs exist | Named authenticated product ingress and independently provisioned trust |
| Ordinary turn composition | Agentd bootstraps registry and installs prompt runtime host | Live callers for enumeration and compile/stage |
| Recovery freshness | Internally validated ordinary restore and independent-cut comparison API | Authenticated/current witness custody refreshed per acknowledged mutation |
| Physical provider send | Staging binds exact bytes/model/deadline; journal records dispatch/order | Current registry and revocation revalidation at actual send |
| Graph and token authority | In-memory relation projection and declared token ceilings | Governed durable relation writes, exact tokenizer attestation, >1K-token P0 review |
| Acceptance and release | No authority is added by any local check | Independent outcomes, target-host qualification, operator acceptance, canary/promotion/release |

Source implementation is substantial but product completion is not established.
Production, activation, acceptance, promotion and release remain false. Prior
source/CI failures and independent external gates are not converted into passes.
