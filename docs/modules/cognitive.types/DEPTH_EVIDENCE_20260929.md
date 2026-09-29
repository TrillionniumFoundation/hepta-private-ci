# Fixed-candidate consumer and fuzz depth evidence

This supplement describes the read-only `.github/workflows/cognitive-types-depth-evidence.yml` execution surface and its verifier in `qualification/cognitive-types-v1/depth_evidence.py`. It does not replace `TECHNICAL.md`, `QUALIFICATION.md`, the existing six-artifact qualification matrix, or `IMPLEMENTATION_MAP.json`. The implementation map remains the product-status authority.

## Preserved design boundaries

The workflow does not add a type source, writer, registry, database, runtime owner, migration promotion path, fallback path, or authority cache. `Validated<T>` remains structural evidence only. Frozen and schema-bound digest profiles remain distinct. `CanonicalHandoffV1` still requires typed equality and actual schema-bound output equality, and the real owner must still revalidate scope, lineage, currentness and revocation immediately before physical use.

No workflow input can change a consumer's migration state. `cognitive.read` and `cognitive.store` remain canonical-shadow consumers; `memory.retrieval`, `compact.engine` and `intelligence.control` remain registered pending cutover until their actual product obligations are independently satisfied. A passing package or owner-path test does not retire compatibility.

## One source/base pair and two deterministic candidates

The resolve job checks out one immutable source SHA, fetches one current base SHA, and publishes both before any matrix fanout. Pull requests exercise the exact source and a deterministic synthetic merge with ordered parents `[base, source]`. Scheduled and manually dispatched runs exercise the exact selected source. A merge conflict, changed parent order, tree mismatch, missing identity, or later source/base substitution is nonpassing.

`depth_evidence.py prepare` uses the same candidate-construction implementation as the module's qualification runner. Every consumer, owner, and fuzz artifact records the source, base, candidate commit and tree, ordered parents, workflow run identity, run attempt, and explicit false values for product acceptance, activation, and release.

## Independently visible consumer and owner paths

For each applicable candidate, the workflow runs separate jobs for the five existing consumers:

- `cognitive.read` → `codex-hepta-cognitive-read`
- `cognitive.store` → `codex-hepta-cognitive-store`
- `memory.retrieval` → `codex-hepta-memory-retrieval`
- `compact.engine` → `codex-hepta-compact-engine`
- `intelligence.control` → `codex-hepta-intelligence`

Each consumer job records the active Rust toolchain and separately retains formatting, all-target check, strict Clippy, and complete package-test logs. A formatting command may be otherwise silent, so the retained log includes its exact exit code. Every check is attempted independently; failed, skipped, missing, timed-out, or cancelled outcomes cannot satisfy the artifact.

The owner matrix separately executes the existing Agentd durable cognitive-store writer test, retrieval-owned canonical recall through the normal Agentd path, and the existing Memory shared-experience owner bridge. These are the existing owners and entrypoints, not replacement executors. The matrix also runs strict all-target lint over Memory and Agentd. It does not authenticate a deployment host or establish that every configured default profile is active.

## Actual decoder fuzz campaigns

The existing 16-contract libFuzzer target is executed rather than merely compiled. Pull requests run bounded campaigns on both the exact source and deterministic synthetic-merge candidates. Manual and scheduled runs use the exact selected commit; the scheduled default-branch campaign provides repeated pressure after integration.

The workflow pins a dated Rust nightly and `cargo-fuzz`, seeds the corpus with a retained canonical V1 envelope, keeps the corpus and findings outside the repository, and places the Cargo target outside both the repository and uploaded evidence. The retained fuzz lockfile is read-only. Any tracked or untracked source mutation rejects. Pull-request campaigns require 180 seconds; scheduled and manually dispatched campaigns require 900 seconds. Different durations cannot be relabelled as the required observation.

A bounded or scheduled campaign is evidence for the named target, candidate, toolchain, corpus, and duration only. It is not exhaustive input coverage, global mutation coverage, a hostile-code operating-system sandbox, authenticated product composition, target-host capacity acceptance, or proof that future revisions are safe.

## Complete artifact sealing and independent aggregation

A job result alone is not sufficient. After execution, each job inventories every regular evidence file with its relative path, exact byte length, and SHA-256 digest. Symlinks, special files, unsafe paths, excess depth, excess file count, excess total bytes, missing required files, extra or modified files, duplicate JSON keys, nonfinite values, identity drift, and lifecycle-claim promotion reject. Failed execution is sealed as refusal evidence rather than rewritten into a pass.

The aggregate job downloads only artifacts from the same source SHA and run attempt. For a pull request it requires exactly fourteen artifacts: five consumer artifacts, one owner artifact, and one fuzz artifact for each of the two candidates. Scheduled and manual exact-source runs require exactly seven. Missing, extra, misnamed, stale, or cross-run artifacts reject.

The aggregator verifies the receipt checksum, rebuilds the complete file inventory, reparses candidate and result records under strict JSON rules, checks source/base/candidate/run correspondence, enforces candidate parent order, verifies event-specific fuzz duration and clean-source status, and then emits a separately sealed matrix decision. The ten adversarial verifier regressions cover complete matrices, missing or renamed artifacts, post-seal modification, resealed identity or acceptance claims, duplicate JSON keys, symlinks, failed outcomes, dirty fuzz source, wrong duration, and synthetic-merge parent substitution.

The evidence verifier is candidate-controlled repository code, not an independent external trust root. It strengthens reproducibility and tamper detection inside the repository boundary; independent acceptance still requires separately governed review and execution.

## Scheduling and duplicate-run control

The original `cognitive-types-qualification` workflow still runs native, consumer, and owner groups over exact-head and deterministic synthetic-merge candidates. Cancellation is nonpassing and transfers no evidence to the replacement run.

The depth workflow has its own aggregate gate. All applicable consumer, owner, fuzz, artifact-sealing, and aggregate-verification steps must succeed. Artifacts are retained for 30 days, including refusal and crash output. This supplemental gate does not update implementation-map lifecycle booleans and is not release authority.

## Remaining product obligations

Even after this workflow passes, canonical product convergence still requires authenticated normal-entrypoint evidence for each deployed profile, current scope and revocation observations at final use, exact output binding, controlled compatibility fallback, rollback rehearsal, selected-host capacity evidence, and independent acceptance. Shared Experience V2 still requires separately governed cross-host transport, owner-epoch authentication, longitudinal transfer, and influence-removal evidence.
