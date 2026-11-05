# PQ evidence recovery owner: scope and validation record

This is a source repair candidate for the mandatory Agentd evidence-recovery
boundary. It does not activate whole-Hepta PQ authorization, deploy independent
recovery roots, or establish rollback-safe external provider effects.

## Exact source range and reconstruction

- Repository: `TrillionniumFoundation/hepta-private-ci`.
- Reviewed source base: `3558ced0fd983603a3082a42359e8da63dfc8418`.
- Base tree: `74366da4b0fe86e55f3c0c48cfb1484035181ba0`.
- Historical native source: `f04033d852ee9c1c9ba88a9fc48c21b798c39f97`.
- Historical native tree: `e6103f5f5fa3f6ba7938f78bc616ad2dd90e6e89`.
- Current publication source R2: `70115620a7f540c8618a9b0d32ead20f8bc508f0`.
- Current R2 tree: `ebd1437475d71252786788f67d2911f5a6e6108d`; parent
  `9e8faef449a4392b7b9aa6a9071f260a34d95ec9`.
- Historical publication source R: `fc0c6f7430cc1cce9274d407536e7249f2290ccd`.
- Historical R tree: `8403d5acabc83707e9b5fcb4e5250a4883c12293`; parent
  `d7c32f38ae1c3890e73ff48ef8ee725ba4e80c58`, preserving incoming schema 0016.
- R2 preserves 229 subsequently published qualification artifact paths and adds
  only the explicit fixture-error conversion described below. Runtime, profiles,
  locks and workflow match the reviewed repair. `R2-source-provenance.json`
  records the 22 current repair-path blobs; it does not promote older native logs.
- Final local source and CI candidate: `7292152e0dd8a592d01110a8b42db4a0deafaf25`.
- Final local candidate tree: `1d3c7d5804202c23a2bdbcb6edddc3e12c174b06`.
- The historical source changes 21 files: Agentd recovery admission, both ordinary
  and qualified-neural entry points, their fixtures, installation documentation,
  and one existing workspace test dependency in `Cargo.lock`. The final local
  candidate additionally tightens authority placement to all four owned roots
  and includes the audited PQ CI workflow, for 22 changed paths against the base.
- `local-source-provenance.json` records every final local changed path,
  base/candidate blob, SHA-256, size and mode. Its full-index binary patch is
  `local-source.patch`. These source identities do not claim native execution.
- `f04033d8-reconstruction.json`, the adjacent full-index binary patches and the
  raw `96e476cd`/`f04033d8` commit objects preserve a reconstructible historical
  source. The f040 local commit is not assumed to be reachable on GitHub.

The historical checkout used sparse materialization. At creation of the historical local
`commit-tree` checkpoints, 1,295 unrelated blobs were unavailable and
`write-tree --missing-ok` was used; that historical step did not establish full
source closure. The later inventory `object-inventory-current.json`, performed
with lazy fetching disabled, found all 11,126 distinct indexed blobs present
(11,310 tracked paths, zero missing). The final two local commits used ordinary
`git commit`. Object availability does not imply a complete working-tree
materialization. The publication source overlaid these changed blobs on the
latest exact remote tree and preserved parallel commits and historical evidence.
After R's second native build terminated, sparse checkout was disabled. The
complete R worktree check found all 11,374 tracked files/symlinks present
(143,936,369 logical bytes) with exact Git blob hashes, zero errors and clean
HEAD/index/worktree state. `R-full-worktree-materialization.json` records that
later closure; it is not attributed retroactively to the earlier sparse builds. The current R2
checkout was also fully verified before native execution: 11,603 tracked paths,
179,185,736 logical bytes, zero missing/hash mismatches and clean source. The
187 missing peer blobs were fetched from their exact published Git identities
and verified before checkout; the complete peer import receipt is retained.

Old qualification, benchmark and native records retain their original source,
feature, profile and environment ranges. They are not promoted to this candidate.

## Repaired admission path

The original frontier accepted an Ed25519 V2 recovery signature. Recovery was
optional at `EvidenceHost::open`; disabling the evidence append API still left
the normal governance/App Server and AuthBus able to open the shared evidence
lineage. The normal App Server enables governance independently of that API.

The candidate requires an ML-DSA-65 `EvidenceRecoveryFrontierV3` and a separately
supplied V2 signer-trust file on every public `run` startup, including an apparently
new host and a host without evidence/AuthBus options. Authentication uses the
existing contracts `PqNativeVerifier`; no new signature algorithm is introduced.
The signed domain is `hepta.kernel.evidence.recovery-frontier.pq.v3` plus NUL.
Profile, store scope, principal, key epoch, key ID and nonzero generation floor
must match. Revoked roots, valid classical V1/V2 signatures, wrong-domain
signatures and mismatched pins do not admit the current PQ recovery boundary.

Each authority file is checked independently against canonical Agent home,
run, workspace and fleet roots. Genuine ML-DSA-signed files inside any of these
explicitly owned rollback domains are rejected. For an absent root tail, the
read-only resolver uses its existing canonical ancestor and retains only normal
missing components; it does not create directories. Broken aliases, access
failures and non-directory ancestors fail closed. This path rule does not prove
independent UID custody or immutable parent directories.

Both executables call the shared public
`preflight_evidence_recovery(&AgentdConfig)` before their bootstrap owners:

- `hepta-agentd` checks before loading plasticity/cognitive process bootstrap.
- `hepta-neural-agentd` accepts the two mandatory frontier flags and checks before
  its original neural model/inference preparation.

The preflight authenticates the external files and compares a fully migrated,
already existing evidence image using the existing read-only store opener. It
does not migrate the database or bind its store ID. Public `run` independently
reloads the authority and repeats the read-only check; after the writable open it
checks the snapshot again before binding and before `AgentdState::new`, runtime
plasticity composition, AuthBus or the App Server can run. Calling `run` directly
does not bypass admission, and an earlier preflight is not a reusable grant.
Configuration loading may already create and lock the existing writer control
file; this is not a claim that the whole process performs zero file writes.

## Breaking deployment requirements

Both `--evidence-recovery-frontier-file` and
`--evidence-recovery-frontier-trust-file` are mandatory. They cannot be omitted by
disabling `--evidence-trust-file`. The old classical frontier wire is historical
input, not an active recovery authority in this profile.

Bootstrap and migration must explicitly stage the intended existing database,
then obtain the recovery owner's signature over that exact image. An absent,
partial or older migration image is refused; ordinary startup does not create an
empty image and silently authorize it. Installer/updater staging and real root
custody/rotation deployment are still separate work.

The external-file identity checks currently require Unix. Windows Agentd now
fails closed at this mandatory boundary until an equivalent native path is
implemented and qualified. There is no classical or unchecked compatibility
fallback. See `codex-rs/hepta-agentd/PQ_INSTALLATION.md` for the precise wire and
deployment fields.

## Regression and fixture scope

The candidate contains nine `evidence_frontier` unit cases: valid legacy V1/V2
signature rejection; signing of both effect fields; real PQ close/reopen;
read-only preflight without binding or changing the image; missing authority at
the public preflight/run entry; wrong domain/profile; scope, epoch, revocation and
generation floor; key pin/canonical signature; and genuine new-key rotation with
old-key retirement. The final scope test additionally exercises eight authority
placement subcases: frontier and trust independently inside each of the four
roots. The read-only test preserves its valid fixture with absent run/workspace
directories and verifies that neither successful nor failed preflight creates them.

All four existing `kernel_evidence_product` cases remain selected: authenticated
writer/query/verifier/terminal composition, exact current image recovery, valid
older qualification image rejection, and provider-effect-only image rollback
rejection. The rollback case signs the current checkpoint before restoring the
old image and also checks that the rejected restored database bytes remain
unchanged.

Process fixtures use real ML-DSA-65 keys and stage their initial checkpoint once.
Restart retains that checkpoint; it neither reads the current database to bless
it nor invokes a signer. Qualified-neural fixtures preserve that rule. Real model
campaigns retain their original ignored status, inputs and budgets; this work
does not manufacture model or external-operator evidence.

The CI selection audit in the adjacent `ci-*` files validates selection and
failure handling using synthetic harness fixtures. The integrated R audit passed
154 expected fixture outcomes and 37 source-name/selector checks while all 12
inputs, HEAD/tree and clean working status remained unchanged. Its first attempt
failed before any fixture because the sparse workflow was absent; that actual
failure is retained. It is not a native Rust test, model execution or independent
deployment result. The audit invocation itself did not trigger remote CI.

R was separately pushed by the publication owner. A single hosted-workflow
readback observed the policy-renewal run queued, native-pair pending and public
initial neural execution in progress. `R-hosted-workflow-readback.json` retains
that observation; it is not a completed or passing hosted CI result. Its recorded
time is the snapshot write time, not a fabricated exact query time.

## Current R2 validation

All entries below refer to `70115620a7f540c8618a9b0d32ead20f8bc508f0` unless
explicitly labeled otherwise. Original profiles, default features and pinned
Rust 1.96.0 remain unchanged.

| Gate | Actual outcome | Scope |
| --- | --- | --- |
| Nine frontier unit cases | PASS, exit 0, 31.491847 s | 9 selected cases executed; 239 other library cases skipped by the invocation |
| Four kernel evidence product cases | 2 PASS, 2 FAIL, 0 skipped; exit 100, 62.546287 s | Both rollback rejections passed; both positive startup/IPC cases failed with Unix socket EPERM |
| CI selection/source audit | PASS, 154 expected fixture outcomes and 37 source names | Synthetic audit only; zero native tests and no hosted CI triggered by this audit |
| Required scoped `just fix` | BUILD_BLOCKED_ENOSPC in both attempts; exit 101 after 368.188540 s and 337.497042 s | Original three-package recipe; no completed lint pass and no source changes |
| Inference-worker-host library tests | BUILD_BLOCKED_LINKER_SIGBUS, exit 101, 107.717685 s; zero tests executed | Original default scope; no ignored real-model campaign was activated |

The two failed product cases are
`real_agentd_composes_authenticated_evidence_writer_query_verifier_and_terminal_observer`
and `signed_recovery_frontier_allows_exact_current_database`. They really spawned
Agentd and failed before readiness because the child could not bind its control
socket. The original local nextest configuration retried both, ending in
`TRY 2 FAIL`. Their positive IPC assertions were not reached. No skip, assertion,
profile, permission or sandbox setting was changed to turn these failures green.

The two passing product cases are
`signed_recovery_frontier_rejects_valid_older_database_image` and
`signed_recovery_frontier_rejects_effect_only_database_rollback`. Their real child
processes were refused under the `recovery_required` oracle, and their restored
database bytes remained unchanged. That oracle is a recovery-required category,
not a claim that a more specific diagnostic appeared in successful test output.

A minimal environment probe was denied at `socket(AF_UNIX, SOCK_STREAM)` itself,
with errno 1 / EPERM; no pathname-dependent bind was reached and no second
location attempt or product rerun followed. This is an environment observation,
not an additional product test or success.

`R2-frontier-native-final.json` and `R2-product-native-final.json` retain the exact
names, commands, nextest run IDs, source identities, log hashes and artifact
identities. The executed unit-only and product-test executables were hashed then
reclaimed after their respective gates. The actual Agentd executable remains
retained locally: 1,232,076,656 bytes, SHA-256
`1fda3237fa995431be7a909e69f938aa0e92ef1f10b80cd425dd2544b5b23d2f`.
The unused browser executable was also hashed and its two verified hardlinks
reclaimed after the product gate ended. The cleanup receipt records the limited
process visibility; it does not claim a universal absence of open mappings.
These are local debug build outputs, not qualified release or deployed artifacts.

The inference-host library build reached its final `cc`/`ld` link and terminated
with signal 7 / Bus error before nextest could execute any test. The raw log does
not contain an ENOSPC diagnostic, and the linker failure's root cause is not
established. Its exact `-o` test executable did not exist after termination.
`R2-infer-worker-lib-classification.json` and its raw receipt/log preserve that
scope; failed or completed native outputs are not described as passing tests.
Only this task's inactive incremental cache was reclaimed afterward, retaining
dependency libraries/metadata, object inputs, source and the actual Agentd binary.

The required three-package `just fix` first failed while writing the
`codex-protocol` incremental dependency graph. After measured cleanup of this
task's inactive caches and unused, verified browser hardlinks, one unchanged
command retry passed that point but failed while writing the
`codex-extension-api` incremental query cache. Both failures explicitly report
ENOSPC / OS error 28. Neither completed the lint gate or changed the source.
The original recipe does not request `-D warnings`; no strict-warning-free
result is claimed. Both receipts and raw logs remain archived. No additional
native retries or ignored model campaigns followed.

The final R2 CI-selection audit independently retained all 12 input blobs and
clean source identities before and after the original validator. It completed
154 expected synthetic fixture outcomes and 37 source-name checks in 6.144
seconds, with zero native tests. See `ci-r2-scope.md` and the adjacent R2
provenance and raw output. A separate hosted-workflow readback at
2026-11-05T06:18:29Z observed policy-renewal run 41979277905 pending;
`R2-hosted-workflow-readback.json` is an observation, not a hosted CI pass.
The audit and readback did not themselves trigger CI.

## Historical native validation and build tooling

The historical native attempt is recorded in
`f04033d8-agentd-frontier-native.json` and `f04033d8-agentd-frontier-native.log`.
It ran for 1,838.714883 seconds and exited 101 while `codex-core` attempted to
write `target/debug/deps/rmetaJGYMjD/full.rmeta`: `No space left on device`
(OS error 28). **BUILD_BLOCKED_ENOSPC; zero tests executed.** This is not a
regression-test failure or a result for the later four-root/incoming-0016 source.
Its command is:

```sh
CARGO_BUILD_JOBS=1 CARGO_TARGET_DIR=/absolute/isolated/target \
  just test -p codex-hepta-agentd --locked --lib -E 'test(evidence_frontier)'
```

It uses the repository's pinned Rust 1.96.0 toolchain, original default Cargo
features/profile and the original `just test` nextest runner. No smaller profile,
mock verifier, feature omission or foreign active target cache is substituted.
The wrapper did not configure a build wall timeout. Its actual exit, executed
test count and elapsed time determine the local result; no timeout or extra
failure criterion is applied retroactively. This cold build did not execute the
original CI lane, whose 600-second test step follows prior compilation. A local
result must not be presented as that CI lane or step having passed.

Formatting and whitespace validation are source-scoped. The historical f040
range passed `just fmt --base 3558ced0fd983603a3082a42359e8da63dfc8418 --check`
and `git diff --check 3558ced0fd983603a3082a42359e8da63dfc8418 f04033d852ee9c1c9ba88a9fc48c21b798c39f97`.

After the four-root changes, `just fmt` was applied and the following checks
returned 0 immediately before the final two ordinary local commits. The checked
contents match local candidate `7292152e0dd8a592d01110a8b42db4a0deafaf25`;
`local-source-format.json` preserves this scope. The commands did not check the
full integrated R tree or execute native tests:

```sh
just fmt --base 3558ced0fd983603a3082a42359e8da63dfc8418 --check
git diff --check
```

`just bazel-lock-update` **passed**, exit 0 in 72.156357 seconds, with the pinned
Bazel 9.3.0 binary and no generated `MODULE.bazel.lock` difference. The binary's
SHA-256 is `d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8`.
The isolated wrapper used foreground `--batch` because the container could not
observe the daemon PID. It supplied a private copy of the Java default trust
store supplemented only by preinstalled system/proxy CA certificates. TLS and
checksum verification remained enabled. `bazel-system-trust.json` records their
fingerprints; no CA material or private trust-store file is included here.

Earlier genuine failures are retained: initially Bazel was absent (exit 127);
the installed daemon could not observe PID 13 (exit 36); sparse local packages
were missing (exit 37); Java initially did not trust the configured proxy CA
(exit 37); one further exact local patch package was absent (exit 37). The final
resolution retries shared the original 600-second budget. All materialized
Bazel inputs came from exact existing Git blobs. The lockfile was not hand-edited.
See the adjacent `bazel-lock-update*.json` and `.log`, `bazel-download.json` and
`bazel-resolution-budget.json` for the actual commands and terminal results.

The successful Bazel receipt did not capture source commit/tree or complete
dirty state at command boundaries. A separate Git object inventory during its
execution recorded HEAD f040; it did not capture the whole dirty checkout.
`bazel-source-scope.json` records this limitation without rewriting the original
receipt. The 72.156357-second success is dependency-lock tooling evidence, not
an execution attributed to complete R2 or a native acceptance result.

After the historical native attempt terminated, only this agent's incremental
cache and later its finished Bazel LLVM download/extraction cache were removed.
The original logs, Rust dependencies, rlibs, rmeta, fingerprints and source were
retained. Cleanup receipts are included. No active Rust process or other
session's cache was removed.

The current native gates use the following commands under exact R2. Each
terminal result is recorded separately above and in its source-specific receipt.
The original f040 record is not reused as execution of a newer source:

```sh
just test -p codex-hepta-agentd --locked --lib -E 'test(evidence_frontier)'
just test -p codex-hepta-agentd --locked --test kernel_evidence_product
just test -p codex-hepta-infer-worker-host --locked --lib
just fix -p codex-hepta-evidence -p codex-hepta-agentd -p codex-hepta-infer-worker-host --locked
```

Product results must report actual child process, IPC and test body execution.
A sandbox/materials early return is not the original product gate passing.
Ignored real-model campaigns remain separate, unchanged obligations.

## Integrated R native attempt history

| Attempt | Actual result | Executed tests | Scope |
| --- | --- | ---: | --- |
| R attempt 1 | Exit 101 after 526.955921 s: missing tracked `docs/modules/MODULES.json` during `hepta-fleet` compilation | 0 | `BUILD_BLOCKED_SPARSE_COMPILE_INPUT` |
| R attempt 2 | Exit 101 after 379.744616 s: final Agentd libtest linker terminated with signal 7 / Bus error | 0 | `BUILD_BLOCKED_LINKER_SIGBUS`; the log does not establish the cause |
| R attempt 3 | Exit 0 after 85.193422 s; actual native run completed | 9 passed; 239 other tests skipped in the selected lib scope | Same exact R, pinned toolchain, original profile and flags; `R-frontier-native-final.json` |

The exact R blob for `MODULES.json` was materialized; a static scan found 194
literal `include_str!`/`include_bytes!` references and no further missing literal
target. This did not change source. The later complete worktree verification also
covers tracked inputs expressed through other include forms.

After attempt 2, the failed link's exact `-o` executable did not exist; there was
no failed executable to retain or hash. Its diagnostic, command, rcgu object
inputs and all dependency outputs remain available. Only the inactive, private
incremental optimization cache was reclaimed. Before/after SHA-256 checks of
core, Agentd and inference-host libraries/metadata agreed. The third attempt is a
single unchanged-source retry following a measured increase in available
storage, with no linker, build profile or compiler-flag workaround. The third attempt passed its nine selected cases. That success does not
convert either preceding build failure into a test execution.

## Product fixture compile repair after R

The first real `kernel_evidence_product` build on R exited 101 after 8.182188 s
with E0277, before any of its four tests executed. The existing provider-effect
rollback fixture used `ProviderEffectKey::for_operation(...)?`, but its
`ProviderEffectBindingError` has no `std::error::Error` implementation for automatic
conversion into `anyhow::Error`. This same call existed in the reviewed 3558 base;
it is a source compile defect, not an environmental or IPC failure.

The minimal successor maps that typed fixture error explicitly into `anyhow`.
Provider, operation, payload, database effect, retained checkpoint and rollback
assertions are unchanged. No production error type or protocol is expanded.
`product-fixture-compile-fix.json` and its patch preserve the exact single-file
change. The published R2 successor received its own nine-case native run and separate
four-case product run as recorded above. R's earlier nine passing tests remain
scoped to R.

## Remaining security and activation obligations

1. **External freshness and root deployment remain open.** A canonical file path
   outside all four owned roots is not an independent failure domain. Restoring a whole
   host together with its trust file and generation floor can restore the old
   authority. Production custody, protected floors, real root rotation/retirement,
   cold recovery and key-fault exercises are not demonstrated by test fixtures.
2. **This snapshot does not cover all real effects.** It projects
   `provider_effect_intents`, `provider_effect_acknowledgements` and
   `provider_effect_uncertainties`. The separate ordinary governance
   `provider_invocation_intents`/`provider_invocation_terminals` and TaskFlow's
   automation database are outside that projection. Default governance Shadow
   paths can still return detached allow decisions. Source references are
   `hepta-evidence/src/recovery_effect_frontier.rs`,
   `hepta-evidence/src/provider_store.rs` and
   `ext/hepta-governance/src/provider_policy.rs` under `codex-rs`.
3. **Other live authorization relationships remain open.** The HTTP/PoN automation
   effect host still has classical `FinalUseAuthority::open_state_dir` paths in
   `hepta-agentd/src/automation_effect_host.rs`. The shared recovery gate does not
   convert every live owner or its operation domain to PQ authorization.
4. **There is no cross-provider atomic commit.** Snapshot comparison, store-ID
   binding and external effects are separate operations. They require runtime
   writer exclusivity plus independently durable provider idempotency and
   reconciliation; this patch does not establish at-most-once external effects
   across crashes, lost replies, concurrent writers or whole-host rollback.
   A concrete remaining window is a retained checkpoint Q0, followed by an effect
   that advances only local state to S1: before an independent owner publishes and
   retains Q1, restoring the Q0-matching S0 can pass this admission. The rollback
   regression signs and retains Q1 before restoring S0. It does not prove atomic
   publication of an external checkpoint for every consumed permission.
5. **Source identities are not binary pins.** The signed source commit/tree
   fields have syntax and signature checks, but are not compared with the
   running binary. Complete pair/lock/binary/config freezing and activation
   responsibility remain separate gates.
6. **Other entry points and original capacity remain open.** Direct non-Agentd
   App Server/governance constructors are outside this startup admission. No
   original WAN/adversarial capacity run or independent subject deployment is
   established here.

Consequently this candidate is evidence for a specific source repair and its
explicit validation range. It is not a P0-2, P0-3, P0-5 or P0-6 completion receipt.

## Archive integrity

`index.json` records every other file in this directory by byte size, SHA-256
and Git blob ID. Raw logs are retained alongside their receipts, including
failed attempts. The index excludes itself. `R2-validation-summary.json` gives
the final source-scoped gate and artifact states; no pending local native
command remains. Hosted CI observations retain their original observation
time and pending status.
