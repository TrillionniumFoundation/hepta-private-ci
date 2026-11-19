# Elevated Windows permission boundary: exact 9bd2 follow-up

**The original elevated outside-delete failure has now been observed twice. Removing broad restricting SIDs is a concrete partial tightening; it is not yet a complete permission repair.** This review made no source/token change and started no host, native test or model request.

The two original runs were 43002359812 on source189 and 43021840561 on source9bd2. Both actual elevated children left Neither intact but deleted the file and directory in TargetOnly, ParentOnly and Both outside cells. The current 27,138-byte raw log has SHA-256 `0f4357942bd12783593f3d0a817d97db7ac3d26395a0bee30f5951ac5672976a`. Its 12 outside object ACLs were independently decoded and contain only Everyone ACEs. The original child token itself was not dumped. Parent-process privilege observations from separate Bazel failures are not substituted for it.

## What can be changed locally, and what it would prove

The exact9bd2 production token/roots/runner/desktop/WFP chain is unchanged from the earlier reviewed189 source. The elevated constructors call `create_token_with_caps_user_and_additional_restrictions_from`, which adds User, then the Include branch adds Logon and Everyone. All these identities are alternative restricting-ACE matches, not additional mandatory capability checks.

A dedicated-account constructor that preserves normal User/Groups, keeps `WRITE_RESTRICTED`, and omits those three broad identities from the **restricting** list is a small source-local tightening. The legacy public constructors cannot be used as a shortcut: they deliberately refuse before token creation. Keeping WRITE_RESTRICTED does not by itself require a new generic read capability—Microsoft documents that restricting SIDs are considered only for write access under that flag.

That change would remove the broad identity alternative, but it would not establish all outside deletion routes. `legacy_admission.rs` explicitly retains the independently observed parent FILE_DELETE_CHILD counterexample. The four-cell test remains the oracle; no refusal assertion, retry policy or timeout should change. A cap-only proposal would also have to preserve actual private-desktop startup and WFP matching. This review neither ran that proposal nor asserts that its parent route has passed.

## Existing implementation and the smallest complete alternative identified

| Existing code | Reusable behavior | Missing requirement if WRITE_RESTRICTED is removed |
| --- | --- | --- |
| `cap.rs`, `spawn_prep.rs:438–452` | Select currently authorized write-root SIDs; stale roots are omitted. | Derive an explicit current read-capability set from the trusted typed profile/root inputs. `caps.readonly` is one persistent SID, not a completed set of read-root grants. |
| `setup_main/win.rs:189–259` | Apply existing read/execute grants to normal sandbox-group identities. | Grant and verify actual read-capability ACEs; existing code skips roots already readable by builtins and never turns those ordinary grants into restricting-capability evidence. |
| `setup_main/win.rs:811–841` | Launch a background read-ACL helper, or skip it when its mutex exists. | Obtain completion for this exact request's necessary read grants before child admission. Helper presence and skipped concurrent work are not an acknowledgement. |
| `setup_main/win.rs:851–951`, `acl.rs:343–347,494–501` | Grant each active write-root capability and refresh away explicit FILE_DELETE_CHILD, using target DELETE inheritance. | Preserve these per-root rights and deny-write carveouts; do not put the shared sandbox group into the restricting list. |
| `token.rs:57–75,531–538` | Default DACL keeps child-created objects usable. | Do not append read SIDs to the undifferentiated capability vector: the existing helper gives **GENERIC_ALL to every supplied SID**. Separate read capabilities from object-control capabilities. |
| `desktop.rs:70–91,146–252` | Own a private desktop; reject cap-only private=false. | Without Logon, existing code gives all restricting SIDs DESKTOP_ALL_ACCESS, including a route marker. Select desktop capabilities explicitly and preserve private=false rejection. |
| `elevated/ipc_framed.rs:59–76`, runner/process/ConPTY | Preserve authenticated parent IPC and retained stdio handles; existing request carries one capability vector. | Carry or derive distinct roles without a caller-controlled downgrade; retain protocol compatibility checks and real launch behavior. |
| `wfp.rs:169–211,315–322` | Account-scoped ALE_USER_ID descriptor and existing route marker. | Prove expected block/allow matching with the final token. The current token test establishes marker presence only. |

Removing WRITE_RESTRICTED also changes the read contract. The current ACL-refresh root list is not an exhaustive proof of all previously normal-ACL-readable objects: `gather_full_read_roots_for_permissions` deliberately filters an ancestor filesystem root while relying on ambient read access. Preserving that behavior under full restriction needs an explicit authorized read scope and completed read grants through the original privileged setup path. Grants on platform or drive roots are additional persistent host-ACL work; silently limiting reads to today's enumerated list would change the contract. Registry and other secured-object startup behavior must be observed under the final token, rather than assumed from filesystem roots alone.

The smallest **complete alternative identified in the current codebase** is therefore a full restricted-token path plus typed and acknowledged read/write/object capability grants through the existing setup and runner. This is a multi-interface source change. It is not a one-line flag fix, and no such change has been implemented or qualified by this report.

## Existing regression points and remaining evidence

Keep the original real elevated four-cell case and the existing command/env/exit case. The latter again reported LEAK in the current original Windows run; it remains an independent lifecycle issue. Keep the setup tests for helper/platform reads, writable-root readability, deny-read propagation, active-root selection and per-SID write-ACL refresh.

The two existing private-desktop mechanism cases use test-only owned-object tokens after checking legacy refusal; they test capability separation/default selection without launching a real child. They omit the shared-route identity case. Likewise, `elevated_token_includes_network_proxy_restricting_sid` checks SID presence, not actual ALE filtering. These green mechanism checks cannot substitute for a final production-token qualification.

A bounded actual child-token classification tied to the original request/helper identity would remove the remaining mechanism ambiguity. Any later new-source qualification must preserve the outside four-cell refusal and show legitimate inside writes/deletes, required reads, deny-read propagation, actual private-desktop/WinSta0 launch, IPC/stdio and network policy. No fixture token, new owner, widened ACL fallback or disabled elevated mode counts as restored product capability.

## Sources and packet

The structured review maps each statement to exact repository paths and line ranges. `SOURCE_INDEX.json` pins 23 complete files at `9bd2f589debdba4a93baa363817c3669cb103721` / tree `c77785ecb368c44ea699769001a47402c9f50591`; original source bytes are included. The packet also retains the current original deletion log and its 12-ACL decode, plus immutable references to the earlier189 evidence.

Primary Windows references: [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken), [Restricted Tokens](https://learn.microsoft.com/en-us/windows/win32/secauthz/restricted-tokens), and [WFP filtering-condition identifiers](https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-condition-identifiers-). These support the API contract, not a claim of an observed new token or repaired execution.
