# E6 Adopt: actual retirement clocks and original authority entry

Status: read-only source review, 2026-11-20. No credential was read or generated; no signature, native task, model call, training update, Cargo command, source edit, host process, or Git ref change was performed. One native filesystem API read retrieved three known source files from the isolated cold checkout. Their exact Git blobs match the retained 673 inventory. The original eight design artifacts, original 34 planned/unexecuted controls, and the separate 12 planned/unexecuted addendum controls remain unchanged.

## Decision

**The original cold path must cross the old writer's actual retirement frontier. It does not wait an unconditional 300 seconds starting at C completion. A new Root cold-task FinalUse grant does not authorize use of an expired Artifact head.**

The source does not justify the universal statement “all Adopt executions are impossible because 300 > 240.” Those durations have different origins. For a particular execution, compare the actual retained writer expiries, actual signed Artifact head expiry, and actual D admission/use time. If that head is already expired, the existing Artifact path correctly refuses; continuing with that same historical head while preserving the original expiries requires a separate, newly authorized Artifact use path. That path is designed but not implemented or provisioned here.

This is an implementation and authority-source gap. It is not a request for the user to repeat their already granted authorization to develop and test the system.

## 1. Exact clock meanings

| Quantity | Source and actual rule | Consequence |
| --- | --- | --- |
| Post-A authority writer lifetime | `ordinary_q24_process_root_tests.rs`: `LIFETIME_MS = 300_000`; `ordinary_q24_process_recovery_tests.rs`: the successor writer receives `issued_at = now`, `expires_at = now + LIFETIME_MS` | In this fixture, 300 seconds is actually assigned to this writer. It is not merely a theoretical maximum. |
| Retirement frontier | `OriginalColdRetirement::observe`: `R = max(previous.writer_binding.expires_at_unix_seconds * 1000, writer.authority_lease.expires_at_unix_ms)` | Both actual old writer clocks must expire. The CURRENT involved here is the protected cognitive checkpoint, not Artifact CURRENT. |
| Real retirement wait | `OriginalColdPhase::wait_for_actual_expiry` rechecks the old daemon/Root/source are dead, rejects clock regression, and waits until actual `now >= R`; `prepare_after_actual_expiry` checks it again | Process exit alone is insufficient. The code sleeps in bounded polling intervals until the frontier, not for a fresh fixed 300 seconds. |
| Other appearances of 300 | Original claim policy uses `maximum_signature_lifetime_seconds = 300`; Root context configuration accepts `lifetime_ms` only in `1..=300_000` | These are maxima/validation bounds. They must not be confused with the observed retirement frontier. |
| Adopt learning envelope | `OriginalPostATrust::original_profile`: `floor(profile_now_ms / 1000) + 240` seconds | It starts when the profile is made, after successor preparation; it does not start when the writer lease is issued. |
| Adopt Artifact input/head expiry | `original_expiry`: `H = min(envelope_expiry_seconds * 1000, retained_current.expires_at)`; the candidate signed head uses this expiry | Head validity is not renewed by later C completion, writer rotation, selection signing, or Root FinalUse signing. |
| NoUpdate original Artifact head | Initial `Artifacts::new` uses `now + 600_000` ms, and the NoUpdate branch retains that original head | This may leave an ordinary valid-head cold route. It is not a claim that any whole NoUpdate cold D has passed. |
| New D phase | After actual retirement, `D_end = min(whole_end, Instant::now() + 120s)`; original D source deadline/lease are 120s; controller authorization is capped by objective, writer and selection expiries | Preparation, new Root work and D share the remaining original phase. The clock is not reset at every step. |
| Whole cold parent | `run_whole_original_cold_d`: `whole_end = start + 480s` | This includes real A/B/C, actual retirement, new Root/daemon and D. No old result can recreate the required process capabilities. |

Let `W` be the actual post-A writer issuance time in milliseconds, and `P` the profile creation time. Ignoring the additional minimum with the old Artifact head only makes the possible head lifetime longer:

`R >= W + 300000`

`H <= floor(P / 1000) * 1000 + 240000`

Thus `H - R <= (P - W) - 60000`, with an additional fractional-second subtraction. If preparation takes less than 60 seconds between W and P, the head is already expired at the earliest legal retirement time. **The code we reviewed does not enforce a universal `P-W < 60s` invariant**, so the constants alone are not a proof for every schedule. A later naturally observed P could leave a smaller positive window; all actual remaining clocks and checks would still have to pass. Adding a deliberate delay to manipulate this relationship would not demonstrate the required expired-head use path.

The ordinary Artifact reader and the unwired grant primitive refuse when `now > expires_at` (their expiry endpoint is inclusive). AuthBus cold `require_current` refuses when `now >= claims.expires_at_ms`; the D fixture separately requires `now < expires` before signing fresh inputs, and the Root/controller checks also reject at equality. These are the existing separate contracts, not a unified rewritten comparison. Equality is not a useful positive D window. A future execution should retain W, the actual cognitive writer expiry, R, P, H, D preparation/admission/use timestamps and the monotonic whole/D ends, without changing them to force a result. This review did not execute such an experiment.

## 2. Three distinct authorization families

| Family | Existing concrete entry | What it establishes; what remains separate |
| --- | --- | --- |
| New D controller authorization | `ColdNextTaskControllerDataV1`, `ColdNextTaskAuthorizationDataV1::require_current`; `RootColdNextTaskAuthorizationFilesV1::open_original/require_current` | An independently installed Root-controlled role and exact signed task binding. It does not create Root custody, a CURRENT writer, a FinalUse token, or Artifact head authority. |
| Root cold next-task FinalUse | `HostAuthorityService::enroll_original_cold_next_task`; `OriginalColdNextTaskContextV1::issue_cold_next_task_grant`; `RootPreparedColdNextTaskGrantV1`; `DeploymentFinalUseIssuer::issue_original_cold_next_task_final_use` | A genuine new original-issuer signature for the exact prepared D intent while the actual issuer/writer scopes remain live. It is not a new Artifact head or an expired-head use permission. |
| Historical Artifact use | Proposed `SignedArtifactColdUseGrantV1`, private proposed policy/reader/operation types | The present primitive is unwired and default-disabled. Relative signature verification produces `AuthorityPosture::DENY_ALL`. There is no installed production policy/custody constructor, issuer, freshness service or effect-capable consumer. |

### Controller entry is not a self-signed scope

`authority_host_cold_authorization_files.rs` is now directly read back from the known cold checkout, exact Git blob `af087eb5644c64ac4baed8d20baefdfb229431d1`.

Its constructor is restricted to the original runtime session, checks `original_root()`, retains three distinct original files (controller, trust, authorization), canonicalizes the controller and authorization encoding, and rechecks the actual files. The underlying `MetadataFile` requires a Root-owned parent, a regular Root0600 single-link file, original descriptors and unchanged identity/content. This is not an ordinary request choosing a trust key.

The controller authorization has a separate purpose, message ID and sequence from the AuthBus objective. `ColdNextTaskBindingDataV1` has no Deserialize implementation. Root rederives it from actual new recipient identity and writer proof, finalized C current/record/cut, configuration, task, target, final intent, complete manifest and selection, objective signing bytes/signature/sequence/expiry, and actual consumer/trust. `require_current` checks the installed role, principal, agent, scope, key/authority epochs, expiry and strict signature. A valid objective alone is not this fourth authorization envelope. The fixture's fixed test signing seed is test data, not an available production signing credential.

### Root grant entry is already typed and physically scoped

The closed chain is:

1. `HistoricalTaskReadRuntime::retain_finalized_cold_history` requires the actual serving new Root and a completed `ReadFinalized` C operation, and retains physical files/cuts. Archived JSON cannot construct `RootFinalizedColdHistoryV1`.
2. `RootColdNextTaskFilesV1::open_original` takes that history capability, retains the exact new recipient, deployment, C/source/target/artifact files and controller originals; input enrollment is one-use through its private retained option.
3. `HostAuthorityService::with_cold_next_task_context` retains actual issuer and writer leases under `DeploymentFinalUseIssuer::with_live_issuer_and_writer`, verifies process/pidfd and original Root configuration, refreshes the real clock, and caps the context by issuer expiry, writer expiry and the existing operation end. It runs both pre- and post-checks even if the operation returns an error.
4. `RegisteredColdNextTaskV1::from_original` requires actual drained C, the full identical selected model, target unwritten/genesis, original CURRENT and retained C consumer evidence. It rederives and verifies the complete independent controller binding. Its existing `open_artifacts` still requires an ordinary current Artifact head.
5. `issue_cold_next_task_grant` checks the registered original attempt and exact prepared genesis/CURRENT cut, durably begins FinalUse Attempted, privately constructs `RootPreparedColdNextTaskGrantV1`, and calls the actual service's issuer. `into_original_parts(self)` also checks pointer identity of that issuer; arbitrary serialized bindings cannot replace the capability.
6. The directly read-back cold `deployment_publication.rs`, blob `99af1bd035b56d0cf82f1caf82f655a6d560156d`, delegates to `issue_registered_final_use` with the admitted binding, actual registration/proof and capped expiry. The original issuer helper requires the retained writer proof and exact provisioned subject/destination/scope policy, reserves its durable sequence before signing, and rejects expiry during signing. Missing policy is refusal, not an implicit provisioning action.
7. Original physical/current checks and durable Issued follow. The existing C/target CAS, independent consumer and later live-generation checks remain required. A later error cannot justify another automatic nonce/signature or erase a real effect.

The cold files above are bound to retained 504/673 source evidence. Supplementary original helper files were fetched at GitHub commit `2b8125e3f89e83aea90620c94cbc441317d4c3d0`; the source bindings distinguish this older baseline. Two helper blobs also match the retained cold ls-tree. No unobserved helper is silently relabeled as a current cold checkout read.

## 3. Minimum useful implementation, without broadening authority

The original new-D controller and Root FinalUse routes can be retained. The missing work is the purpose-specific Artifact route and its joining points, not a replacement of the original Root authority chain.

**First, a real purpose policy and custody boundary must exist.** The existing Artifact `head_signers` verifier authenticates head-role signatures; it does not install a new purpose policy or possess a production signer. Introduce a private producer of an `OriginalArtifactHeadPolicyContextV1`-equivalent only from independently provisioned original Artifact authority, with actual custody identity and a durable nonce/signing journal. No public constructor accepting arbitrary trust/scope, test key, generic Root grant or tool transport identity may produce it. If this source is absent, the product constructor must continue to refuse.

**Second, supply current revocation/withdrawal/policy evidence after writer retirement.** The retained withdrawal floor and unchanged old physical file protect integrity and rollback, but a retired writer's frozen file does not establish present freshness. The new policy must specify a real live authority/session or authenticated challenge response, persistent consumer floor and offline behavior. Dataset withdrawal, head-purpose policy and key revocation roles cannot be conflated. Either implement a real common ordering/fence for revocation and effects, or a genuinely authorized bounded propagation policy; this review does not choose or invent a new duration.

**Third, build a scoped historical reader and separate selection.** Reuse private signature/history/content verification without exposing `allow_expired`, clock backdating, `into_current` or writer conversions. Keep generic current/head expiry behavior unchanged. The new historical artifact fact and independent selection must bind full model/content, original C conditions, new D recipient/task/runtime/operation, grant/policy, and current withdrawal state. They must remain private, non-cloneable/non-serializable/non-Send operation facts.

**Fourth, join these facts inside the real Root operation and the generation/live-use path.** The proposed cold-use operation must borrow the existing context and finalized C. It must preserve the full original controller binding, exact intent, predecessor drain/genesis, original FinalUse, nonce, CAS, consumer and every later runtime guard. Existing ordinary `AgentdSelectedGenerationV1` and `GenerationArtifactOwnerV1::Writer/RootInitial` cannot serve as an unchecked conversion. Dedicated purpose-specific selection/preparation/live owner surfaces are required; the final native dispatch/output boundary must actually consume the current purpose authorization.

**Fifth, keep the dependency graph acyclic and complete.** Use a new versioned early D descriptor, then Artifact grant, independent selector, final Root intent, independent controller authorization, then a final admission record over all actual bytes/file identities. That final record is an output fact, not its own input or an authorization. Do not strip old configuration fields, omit the fourth envelope or change old wire-v1 meaning. The addendum already states these requirements; it is not their implementation.

These are separable reviewable implementation increments. Only after the missing original policy/custody/freshness producers and all consumers are real should the original whole cold case be executed under the unchanged 240/300/120/480 contracts. NoUpdate's valid-head path remains independent.

## 4. Minimum rejection gates for such an implementation

These are recommended gate groups, not executed tests and not replacements for the frozen 34 + 12 controls:

1. Default-disabled or missing real policy/custody/freshness producer refuses even with a mathematically valid signature. Writer-only, selector-only, Root or transport identities cannot act as Artifact head-purpose authority.
2. Missing/substituted fourth controller envelope, objective used in its place, changed scope/recipient/epochs/intent/selection/configuration/C cut or consumer is rejected before a Root use nonce or effect.
3. Wrong physical file, symlink/hard-link/alias, altered original bytes or C history, current writer mismatch, non-genesis D or a second task input fails the original closed constructors.
4. Time controls use independently recorded actual origins: before R, dead-but-unexpired writer, expired head, equality at D authorization expiry, lost clock/clock regression, exhausted D/whole end. No fixture extends any original lifetime.
5. Private capability and caller gates prevent public construction, Clone/Deserialize/Send, cross-await escape, generic CURRENT/writer/learning conversion or a fallback to ordinary update.
6. Grant/selector/intent/controller/final-record tampering and indirect cyclic hashes fail; all four distinct mandatory late roles remain complete.
7. A stale unchanged withdrawal file after original writer exit, old challenge/session replay, revoked key/policy, rolled-back persistent floor or unavailable freshness source fails at the real operation/effect boundary.
8. Revocation/effect ordering, signature lost ACK, durable Attempted/Issued recovery, post-check failure and CAS uncertainty preserve actual effects and refuse redispatch; they do not report a performed action as zero.

The relevant original groups are CU-01..CU-34 and AD-01..AD-12. All remain planned/unexecuted for this proposed new primitive. Source reading and hash verification here do not add to any native or experimental control count.

## Evidence and limits

`READOUT.json` records the conclusions and zero execution counters. `SOURCE_BINDINGS.json` and `SOURCE_ANCHORS.json` bind actual bytes and specific symbols; `originals/` retains the original three-file host response, its immutable file versions, the failed exact GitHub blob lookup, and the public-base fetches. An initial local-copy extra-newline error was detected by Git hashing and corrected from the retained tool text before review; that correction is preserved separately. No host file was written.

This is a read-only source audit, not compilation, current deployment-custody attestation, a new authority grant, or an Adopt/cold-D success. No new proof-of-useful-work, learning improvement, production qualification or completed experimental stage follows from it.
