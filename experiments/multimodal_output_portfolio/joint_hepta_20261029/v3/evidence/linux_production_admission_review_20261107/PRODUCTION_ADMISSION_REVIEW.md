# E17: production admission after the Linux41 precursor

## Decision

There is no justified dispatch-only production repair at the reviewed main head. The missing object is a **trusted, operation-long host-view authority**, not another successful pathname or link-count sample. Linux41 supplies a test-private guard design and a source-bound owning-target result; it does not construct that authority or enable the production method.

I do not recommend a new product patch that changes the non-macOS override or the advertised capability yet. The next implementable work can close individual prerequisites, but none of the currently established inputs permits it to return an authorized file honestly. This is a conclusion about the reviewed call chain and evidence, not a claim that Linux admission is impossible or that an arbitrary line limit makes it impossible.

This review adds no candidate, source change, native execution, syscall experiment, capability, permission, retry, timeout, test skip, or altered assertion. It does not rerun any historical observer, archive reader, or private execution-log parser.

## Fresh source boundary

The fixed comparison head is main #5268, `a24bb9a6b3d251c54f5973325998a4c21289fe09`, tree `ab7a5108639f89bb474ecbd5660850836b9bdf0a`. Fresh GitHub commit/contents responses bind thirteen selected source bodies. `SOURCE_BINDING.json` and `SOURCE_BINDING_ADDENDUM.json` record each byte identity and the exact scope; this is not a reconstructed whole-tree audit.

The production local filesystem, original authorized-read tests, permission matcher, filesystem trait, environment constructor, helper route, capability publication, regular-file opener, and skills provider remain byte-identical to their frozen reviewed versions. The fresh runtime-path source contains only the Codex executable and optional Linux sandbox executable paths. It has no namespace, mount, task-root, or authority-lifetime field.

The direct `exec-server/src` listing at this head does not contain `read_delegation_guard_tests.rs`. Linux41's test source belongs to the separate source head `73e87c4c4dadc154c6b295d8935df2157f817951`, tree `f22f620a44ab73c96f283f60eb98e92006896f22`. The absence in main is recorded as an observation, not as a request to merge the precursor blindly.

The kernel analysis remains bound to Linux v7.0 commit `028ef9c96e96197026887c0f092424679298aae8`. Five relevant source files were rehashed against the frozen indexes. That identity is not the running kernel of the RBE action, a GitHub runner, or a future product deployment.

## The three original failures require positive reads

The frozen #5165 source-linked failure review binds run `42304403498`, GNU job `128191497954`, and musl job `128191497933`. The matching inner case blocks do not count as independent platform experiments. No private console was read for this follow-up.

| Original case | Proven failure boundary | Behavior a real repair must retain |
| --- | --- | --- |
| `restricted_executor_skill_can_read_permitted_reference` | The final permitted reference is a failure string and cannot be decoded as the expected JSON. Earlier instruction/list checks were reached. | Return the complete permitted reference through authorized admission. |
| `restricted_executor_skill_is_listed_only_when_permitted` | The permitted/denied listing checks already passed; the failure is the final permitted reference JSON decode. | Preserve the denied listing and make the permitted read succeed. |
| `restricted_executor_skill_rejects_reference_until_permission_approved` | The original denial and no-secret-marker checks passed. A turn-scoped read grant was returned, but the next read still lacked the reference marker. | Keep the first denial; read the same locator after the original grant. |

The approval fixture deliberately uses an ordinary symlink from the workspace locator to an external reference file. Its positive outcome rules out putting `RESOLVE_NO_SYMLINKS` on the initial locator open A. A may follow ordinary symlinks in the qualified root view while rejecting magic-link imports. B must strictly reopen the resolved target with the original all-component no-symlink requirement.

Changing these cases to tolerate `Unsupported`, changing their permission grants, or returning the generic stream would not close E17.

## What is actually missing from the production call chain

`Environment::local` constructs `LocalFileSystem::with_runtime_paths`. That object holds the unsandboxed implementation and an optional `SandboxedFileSystem`; neither is a host-view authority. `FileSystemSandboxContext` supplies the original permission profile, cwd, and workspace roots, not a promise about mount or task-root lifetime.

The skills provider calls `read_file_bounded_authorized` whenever a sandbox context is supplied. The current non-macOS override returns `Unsupported` before touching the locator or its authority. The environment capability remains false; the remote path also checks that capability before the authorized-read RPC. Enabling either location without an admitted-handle constructor would bypass a deliberate failure boundary.

The generic helper route is not the missing constructor. Its launch policy adds helper runtime access; its `Open` request uses the ordinary regular-file opener and transfers an FD. Receiving that description proves custody of an FD, not all-component strict reopening, original unaugmented policy acceptance, or a common admission instant in the host view.

## New implementation finding: task-root isolation is smaller than mount authority

A fresh dedicated worker could use `unshare(CLONE_FS)` before capturing root/cwd and beginning admission. The fixed kernel's `unshare_fs` copies `fs_struct`, and `ksys_unshare` installs it for the calling task. This can prevent later root/cwd/umask changes through other threads' shared `fs_struct` from changing that worker's context. It should not be performed on a reusable blocking-pool thread whose changed state could escape the operation.

That is a codeable narrow prerequisite, **not a full-root or mount-lifetime proof**. It copies the current root even if it is a movable chroot/subdirectory bind. The same kernel's `copy_mnt_ns` returns the existing namespace when `CLONE_NEWNS` is absent. The directory and mount objects remain shared, so copying `fs_struct` neither freezes ancestors nor prevents relevant mount changes.

Adding `CLONE_NEWNS` is not an interchangeable implementation detail: the documented operation requires mount-namespace authority. Adding a new user namespace to obtain such authority changes the execution/security context and has thread constraints. No new privileges, user namespace, mount operation, or deployment assumption is authorized or proposed by this review.

Primary references: [fixed `kernel/fork.c`](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/kernel/fork.c), [fixed `fs/namespace.c`](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/fs/namespace.c), and [the Linux `unshare` manual](https://man7.org/linux/man-pages/man2/unshare.2.html).

## New implementation finding: mount observations are obtainable but do not grant a lease

The fixed v7.0 `statmount` implementation does not impose one unconditional `CAP_SYS_ADMIN` test on every use. Its ordinary current-namespace branch permits a reachable mount subject to the remaining checks; its FD branch obtains the mount from the supplied live file description and follows a different reachability path. This is a source-level opportunity for conservative observation without inventing a privilege grant. A denial or missing field still has to fail closed.

Three limits prevent converting the result into a trusted constructor:

1. For a detached FD mount, the kernel deliberately clears the requested mount-point and namespace-ID fields. A successful syscall alone therefore does not establish an attached mount or namespace membership; the returned field mask matters.
2. The FD branch can inspect a mount obtained from an existing description. That does not prove the description was opened by the original root resolver or was not imported from another view.
3. The source explicitly permits mount flags and mount ID mapping to change while it holds the namespace read side. More generally the syscall returns observations; it does not retain namespace locking across later path observation and policy evaluation. Matching before/after IDs cannot establish an uninterrupted interval or eliminate an ABA change.

Thus a future `HostViewObservation` may record measured root/mount facts and reject disallowed shapes. It must not be named or typed as an authority merely because these fields look acceptable. No such new helper was written or executed here. The analysis uses the fixed source, rather than importing later ABI fields or the newer `OPENAT2_REGULAR` flag from current manual pages.

Primary reference: fixed `fs/namespace.c`, especially `statmount_mnt_root`, `statmount_mnt_point`, `do_statmount`, and `SYSCALL_DEFINE4(statmount, ...)`.

## Minimal closed prerequisites and the remaining constructor hole

| Component | What can be implemented without weakening the contract | What it still cannot establish |
| --- | --- | --- |
| Captured original policy | Clone/materialize the original profile/cwd/workspace once, retain original lexical and glob deny evaluation, and reject an unsupported exact-deny-alias class before payload use. | A concurrently mutable canonical deny root cannot be made fixed by cloning the policy value. |
| Isolated task-root context | A dedicated worker can isolate its `fs_struct`, capture its own root/cwd, and retain cleanup ownership. | A copied subdirectory root is still a subdirectory; shared mount topology is not frozen. |
| Resolver origin | Starting from a qualified root FD, A can explicitly forbid magic links; B can additionally forbid every symlink and require live same-inode identity. A narrow class may reject mount crossings using `RESOLVE_NO_XDEV`. | Resolver flags do not establish where that starting root came from or extend their checks into a later authorization interval. |
| Private A guard | Reuse the reviewed one-acquisition, no-clone/no-exposure, directed-signal, consuming-final-query design; only final `F_RDLCK` succeeds. | Leaf delegation does not freeze an unrelated deny alias, an ancestor path, or mount topology. |
| B and bounded result | Keep A/B live, observe a coherent reachable path after B exists, apply original authority, finally validate A, then return B for the original bounded complete read. | This sequence requires the missing trusted root/mount and policy premises before it can authorize anything. |

The smallest genuinely missing **interface contract** is a private executor-owned host-view object with an identified producer and lifetime. Its producer must establish a trusted namespace/root, a supported attached full-root filesystem view (or a separately proved alternative), and the absence of relevant topology substitution throughout admission. Its consumer must not accept an RPC boolean, namespace ID, caller-supplied FD, pathname prefix, or two matching samples as a substitute. External mount administrators may be excluded by an explicitly reviewed deployment/threat contract, but that exclusion cannot be silently inferred from `LocalFileSystem::with_runtime_paths`.

No such producer exists in the thirteen reviewed production sources. Consequently, an implementation of just the table's first four rows would be a precursor, not a safe activation patch. I do not recommend installing dead production scaffolding or calling a function that always rejects a completed fix. The first decision needed is the supported deployment/root authority and its actual owner; once that is concrete, its constructor and admission consumer can be split into small review units without falsifying either unit's claim.

## Exact policy-alias prerequisite

`ReadDenyMatcher::build` stores lexical and canonical spellings of exact unreadable roots. `is_read_denied` also canonicalizes the candidate path. A guard on the target inode does not protect a different symlink used by a deny rule.

For example, a configured deny alias can point elsewhere when the matcher is built, point at the target at the proposed admission instant, and return to its first value for a later sample. The target's leaf delegation and link count can remain intact throughout. Running the original matcher unchanged does not by itself prove the alias had the captured meaning at the chosen instant.

A conservative supported class with no exact unreadable roots after **original** materialization can remove that specific source of instability while retaining original deny globs and malformed-pattern rejection. This is eligibility narrowing, not a general policy implementation or permission to drop deny tests. The original fixture configurations have no explicit exact deny entry, but the actual materialized request still must be checked. Broader profiles need a real lifetime mechanism for their aliases or a separately reviewed semantic change.

Primary reference: [fixed current permission source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a24bb9a6b3d251c54f5973325998a4c21289fe09/codex-rs/protocol/src/permissions.rs), `ReadDenyMatcher`, `get_unreadable_roots_with_cwd`, and `normalized_and_canonical_candidates`.

## Runtime and original-oracle conditions still required

The constructor design alone cannot qualify every Linux filesystem. The actual file must support the exact delegation semantics and the caller must satisfy the unchanged filesystem-UID/ownership, LSM, and conflicting-open rules. An ordinary lease is not a substitute; granting `CAP_LEASE` is not part of this proposal. Kernel/source-version labels or a successful compilation are not those runtime facts.

Linux41's two labeled jobs used the same RBE binary and test action. The owning target passed in 9.7 seconds without a cache marker, while both whole jobs failed. Per-case stdout/XML and the three `DELEGATION_CASE` records are unavailable. The source does **not** skip `Unsupported`: any unsuccessful subcase makes its final success predicate false. That source fact should be preserved alongside the evidence limit; it is not a new direct observation of any subcase or the worker's kernel/mount identity.

Before enabling production, the actual admitted-handle operation must satisfy the three original skills outcomes and the preserved handle/provenance oracles: initial hardlink ambiguity rejects; ordinary allowed symlink resolution works; denied target/glob and parent symlink/decoy reject; same-inode admission is established before payload; overflow returns no partial prefix; later pathname replacement or hardlink creation does not revoke an already admitted handle. A continuous uniqueness requirement during the entire payload read would change the existing positive contract.

Unsupported or refused constructor conditions must remain explicit failures. They cannot be counted as passed positive cases, retried until favorable, or masked by changing a capability, test gate, permission grant, or helper policy.

## Read-only scope and practical next step

This follow-up used fresh selected-source GitHub reads, fixed-source inspection, byte/hash comparisons, and report generation only. It did not inspect private consoles or execution ZIPs. The Linux41 target conclusions are taken from the already frozen owner/peer/root metadata reviews, without replaying their parser.

The practical next step is to settle the host-view producer contract against the actual executor deployment and retain the conservative policy class explicitly. The private guard and strict resolver can then be integrated under that authority. Until then, E17 and all three positive read outcomes remain open. More samples of the same leaf or a new native run without a different discriminating predicate would not fill this constructor gap.

Related frozen inputs:

- `round3_ci/restricted_skills5165/SOURCE_LINKED_FAILURES.json`
- `round3_ci/restricted_delegation_followup/COMMON_ADMISSION_REVIEW.md`
- `round3_ci/restricted_delegation_followup/host_addendum/HOST_NAMESPACE_ADMISSION.md`
- `round3_native/linux_delegation_prerequisites_review/REVIEW.md`
- `round3_native/linux_delegation_guard_41/review2/manifest.json`
- `round3_ci/independent_reviews/linux_delegation41_native/REVIEW.json`
- `round3_local_qualification/linux41_native_root/ROOT_REVIEW.json`

The historical assertions, refused donor, earlier reports, side source, and native qualification limits are unchanged.
