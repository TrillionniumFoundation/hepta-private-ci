# Fixed-candidate consumer and fuzz depth evidence

This supplement describes the read-only `.github/workflows/cognitive-types-depth-evidence.yml` execution surface added on 2026-09-29. It does not replace `TECHNICAL.md`, `QUALIFICATION.md`, the six-artifact qualification matrix, or `IMPLEMENTATION_MAP.json`. The implementation map remains the product-status authority.

## Preserved design boundaries

The workflow does not add a type source, writer, registry, database, runtime owner, migration promotion path, fallback path, or authority cache. `Validated<T>` remains structural evidence only. Frozen and schema-bound digest profiles remain distinct. `CanonicalHandoffV1` still requires typed equality and actual schema-bound output equality, and the real owner must still revalidate scope, lineage, currentness and revocation immediately before physical use.

No workflow input can change a consumer's migration state. `cognitive.read` and `cognitive.store` remain canonical-shadow consumers; `memory.retrieval`, `compact.engine` and `intelligence.control` remain registered pending cutover until their actual product obligations are independently satisfied. A passing package or owner-path test does not retire compatibility.

## Independently visible consumer paths

For each pull-request candidate, the workflow runs separate jobs for the five existing consumers:

- `cognitive.read` → `codex-hepta-cognitive-read`
- `cognitive.store` → `codex-hepta-cognitive-store`
- `memory.retrieval` → `codex-hepta-memory-retrieval`
- `compact.engine` → `codex-hepta-compact-engine`
- `intelligence.control` → `codex-hepta-intelligence`

Each consumer job binds its evidence to either the exact source commit or GitHub's verified two-parent pull-request merge candidate. It records the active Rust toolchain and separately retains formatting, all-target check, strict Clippy and complete package-test logs. Every check runs even when an earlier check fails; the sealing step rejects failed, skipped or missing outcomes and keeps `product_acceptance`, `compatibility_retired`, `activation` and `release` false.

The owner matrix separately executes the existing Agentd durable cognitive-store writer test, retrieval-owned canonical recall through the normal Agentd path, and the existing Memory shared-experience owner bridge. These are the existing owners and entrypoints, not replacement executors. The matrix also runs strict all-target lint over Memory and Agentd. It does not authenticate a deployment host or establish that every configured default profile is active.

## Actual decoder fuzz campaigns

The existing 16-contract libFuzzer target is now executed rather than merely compiled. Pull requests run bounded campaigns on both the exact source and pull-request merge candidates. Manual and scheduled runs use the exact selected commit; the scheduled default-branch campaign provides repeated long-term pressure after integration.

The workflow pins a dated Rust nightly and `cargo-fuzz`, seeds the corpus with a retained canonical V1 envelope, places the corpus, findings and Cargo target outside the repository, makes the retained fuzz lockfile read-only, and rejects any tracked or untracked source mutation. It retains candidate identity, toolchain identity, campaign duration, corpus, crash artifacts, complete console output and final clean-tree status even when the campaign fails.

A bounded or scheduled campaign is evidence for the named target, candidate, toolchain and duration only. It is not exhaustive input coverage, global mutation coverage, a hostile-code operating-system sandbox, authenticated product composition, target-host capacity acceptance or proof that future revisions are safe.

## Scheduling and duplicate-run control

The original six-artifact `cognitive-types-qualification` workflow still runs native, consumer and owner groups over exact-head and deterministic synthetic-merge candidates. Its concurrency key now uses the source branch name for both push and pull-request events, so two events for the same branch cancel duplicate heavy work instead of running two equivalent matrices. Cancellation is nonpassing and transfers no evidence to the replacement run.

The depth workflow has its own aggregate gate. All applicable consumer, owner and fuzz jobs must succeed. Artifacts are retained for 30 days, including refusal and crash output. This supplemental gate does not update implementation-map lifecycle booleans and is not release authority.

## Remaining product obligations

Even after this workflow passes, canonical product convergence still requires authenticated normal-entrypoint evidence for each deployed profile, current scope and revocation observations at final use, exact output binding, controlled compatibility fallback, rollback rehearsal, selected-host capacity evidence and independent acceptance. Shared Experience V2 still requires separately governed cross-host transport, owner-epoch authentication, longitudinal transfer and influence-removal evidence.
