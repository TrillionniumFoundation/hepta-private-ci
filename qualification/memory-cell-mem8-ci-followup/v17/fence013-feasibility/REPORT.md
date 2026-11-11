# Fence v0.13 feasibility review against the original v0.10 failure

**A fixed-pin, separately qualified upgrade is a concrete candidate. This review does not establish that it repairs the original failure.** The new source has directly relevant bounded acquisition handling and safe failure diagnostics, while preserving the complete-observation rejection function and its fixed scan limits. It also contains broader security and lifecycle changes. This is a scoped source review, not a full security audit or an executed Fence qualification.

No source ref, existing workflow, host, service, model request or CI run was changed. The only proposed repository delta is one pinned Action line in a separate local candidate.

## Original and current failed observations

The older original job 130526677869 at source 9bd2 stopped before Fence readiness with `local_control_inventory_unavailable`. Its full 3,859-byte log and original static review remain unchanged. The new c895 original job 130619112490 in run 43048568477 repeats that same error before checkout. Its full log is 3,862 bytes, SHA-256 `f133870c1951e334551c0d9e5baa24279473add86d9fd537703636389b48b30b`.

Both observations used the pinned v0.10 Action, audit mode, Ubuntu 24.04 and no additional allowlist entries. The subsequent missing local clean-worktree Action and missing post-job mount evidence are consequences of the failed setup/skipped checkout. They do not identify a separate original inventory reason.

The original scan's exact unavailable inputs, ownership detail and phase were not retained in those job logs. They remain UNKNOWN. A successful or more informative later run would be new evidence, not settlement of either original scan.

## Immutable source and bundle binding

| Item | Independently read identity |
| --- | --- |
| Original complete Action | `e6b39c80c51cb2b2a39448ddeff74b3b886c0a63` |
| Original reviewed source parent | `735375fadb54cc11a7d2d10642b3150f93fe8720` |
| New reviewed source | `64acdc94f531728494efbdf2d8f05faa26e90f7a` |
| Recomputed new source tree | `228ce4925c73cf194b76094cbaf70494f2ff4ad9`, 1,935 leaves |
| Complete v0.13 Action | `c7675fea986c29f1d655753a7a61fd6b4141be8f` |
| Recomputed complete Action tree | `e19987188c430cdbf901557955ca537a644bbbbd`, 1,937 leaves |
| Bundle manifest blob | `3f0b00d990f9eca9b630feae63f5b6803379bb03`, 592 bytes |
| Binary Git blob / declared size | `77eb796b522a7ae83eb83c42d579f85a41945b3d` / 2,203,880 bytes |
| Manifest and release-asset declared binary SHA-256 | `1a1ac7ad60216e7803403645c202e8c8a4e738326350ce340f8138df1c9a5e04` |

The [immutable v0.13 release](https://github.com/openai/fence/releases/tag/v0.13.0) was published on 2026-11-09 at 19:44:13 UTC. Its source and complete-Action mapping agrees with the raw commits and manifest. The complete Action is a one-parent child of the reviewed source. An independent full-tree reconstruction found exactly two added leaves: the binary and bundle manifest; all other source/wrapper bytes are identical between these two commits.

**Binary readback limit:** the connector returned empty content for this greater-than-1-MiB binary, and the raw blob route rejected non-UTF-8 content. The binary digest above is a matching manifest/release declaration, not a locally computed digest of downloaded binary bytes. No reproducible-build or attestation verification is claimed. The actual Action's [bundle validation](https://github.com/openai/fence/blob/c7675fea986c29f1d655753a7a61fd6b4141be8f/action/lib.cts#L1416-L1483) checks the exact schema and hashes its bundled binary before use. A future qualification must retain its actual Action/binary identity and result.

## Directly relevant changes and remaining strict checks

### 1. Incomplete acquisition is resampled within the original limit

The new [observation loop](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/src/local_control.rs#L1700-L1752) no longer treats a matching but unavailable acquisition pair as an immediate final observation when bounded attempts remain. Acquisition errors may consume the remaining attempts. Known ownerless listeners may be resampled only if the rest of that particular startup inventory is valid.

This does not mark an incomplete observation complete. The final verifier still rejects unavailable, unstable, over-bound, missing ownership and missing reachability. Both `verify_complete_local_control_observation` (1,610 bytes) and `verify_local_control_observation` (288 bytes) are byte-identical to the old source. All eleven original public constants are identical, including three attempts, a 50-ms sampling interval, the 5-second observation timeout, and the process/FD/listener limits.

[MissingOwnerRetry](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/src/local_control.rs#L1655-L1697) is specifically a retry predicate. It does not grant acceptance. Baseline comparisons preserve socket keys, process pins, remaining owners and the relevant container constraints. The normal verifier is still invoked after the observation, including in audit mode.

The source includes persistent-unavailable and mixed-sample negative controls, and tests that bounded, malformed and unreviewed observations do not obtain this exception. These tests were read, not run by this review. Upstream [PR #217](https://github.com/openai/fence/pull/217) documents this startup-only correction.

### 2. The failure now carries bounded, non-identifying diagnostics

The new [diagnostic emission](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/src/local_control.rs#L1559-L1652) exposes scan status, attempt count and closed unavailable/bound enums. When socket ownership is the sole unavailable input and bounds remain intact, it can add a fixed startup phase and a small set of ownership reason labels.

The [Action parser](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/action/main.cts#L180-L218) rejects long or malformed journal lines, unknown reason values, duplicates and inconsistent combinations. It forwards fixed classifications instead of raw journal content, process names, socket names or paths. The ordinary setup error includes recognized detail; enabling a debug secret is unnecessary for those fixed fields. The failing readiness check remains a failure.

This directly addresses the diagnostic gap in the original record. It cannot manufacture a subreason for an already completed v0.10 failure. See [upstream PR #225](https://github.com/openai/fence/pull/225) and the exact [troubleshooting contract](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/docs/troubleshooting.md).

### 3. TCP inventory and exact activation identities also changed

The new [TCP collector](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/src/local_control.rs#L2574-L2705) requests listening TCP sockets directly from the kernel. It validates the sender, sequence, family/state, bounded byte/row counts and successful multipart completion. Interrupted or error dumps remain unavailable rather than becoming an accepted partial inventory. This avoids making unrelated connection-table pressure part of listener inventory, but the original logs do not prove that this was their cause.

The new [UUID/Snap activation rules](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/src/local_control.rs#L891-L956) recognize a tightly described active/idle transition, not arbitrary additional owners. Snap's two named endpoints keep their socket inodes and original systemd process pins. The daemon requires a protected exact package executable, exact service cgroup, root identity and consistent process pin across the two sockets. A daemon replacement while continuously active is rejected; an observed idle interval is necessary before replacing the daemon pin. Split owners, anchor drift and incomplete ownership remain negative cases. [PR #230](https://github.com/openai/fence/pull/230) is the upstream change.

These are changes to the reviewed host-state model. They must not be described as an entirely unchanged accepted-owner set, and the old error does not prove a Snap or UUID cause.

### 4. Audit and the hosted profile do not bypass preflight

The exact Action input schema, configuration parser, CLI, error definitions and activation-plan source are unchanged Git blobs. The new [protected-run path](https://github.com/openai/fence/blob/64acdc94f531728494efbdf2d8f05faa26e90f7a/src/dns_mediator.rs#L3569-L3605) still verifies the reviewed profile, host and initial local-control inventory before the audit/block branch. Audit then verifies its own complete baseline.

Ubuntu 26 support adds reviewed layout/identity branches and socket-sealing logic; the proposal retains the existing Ubuntu 24.04 job. The broader release also changes DNS/readiness, action mount ownership and cleanup handling. The 82-file source comparison spans 169 commits from the old reviewed source, so it is not a minimal upstream diagnostic-only release. This review does not certify every one of those changes.

## Small repository proposal, not yet admitted

The local `candidate/.github/workflows/blob-size-policy.yml` changes only:

```diff
-      - uses: openai/fence@e6b39c80c51cb2b2a39448ddeff74b3b886c0a63 # pin@v0.10.0
+      - uses: openai/fence@c7675fea986c29f1d655753a7a61fd6b4141be8f # pin@v0.13.0
```

Preimage `d870b6f9c1e025aff458c32f0461c752fcd2f0b3` was independently fetched at exact c895. Candidate postimage is `7e01fc010f7c5dd48a2d5f688283e8795436fdcf`, 1,809 bytes, SHA-256 `4a0f656d386d3a9ddc1478c111e09105486cd8cff7e71cb0911c8bd4068ceafd`. The inverse one-line substitution recovers the complete original bytes.

The proposal preserves first-step ordering, Ubuntu 24.04, audit mode, no added allowlist, contents-read permissions, the 30-minute job budget, exact checkout pin, credential persistence disabled, original comparison range, original blob-policy tests, 512,000-byte threshold, original blob allowlist and final clean-worktree gate.

A separate original qualification could check readiness and original downstream/post gates on this exact Action. If setup still fails, the fixed diagnostic fields may establish the *new* failure reason. Any unknown admission or outcome must retain its identity rather than being retried under another key. This proposal does not authorize such execution.

## Verdict

There is concrete, source-backed value in separately qualifying this exact fixed pin: the old missing diagnostic is implemented, bounded retry retains the original completeness gate, and activation recognition is tied to exact identities. There is no evidence yet that c895's original failure is repaired, no proof of its old subreason, and no basis to declare all Fence policy/lifecycle changes safe solely because the release is newer.

The original blocker remains open until an authorized, source-bound qualification actually completes. No network/privilege allowlist, mode, assertion, threshold or guard is relaxed in this repository candidate.
