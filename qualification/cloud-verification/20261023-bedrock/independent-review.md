# Independent Bedrock integration review — provisional candidate review

Base: `74ba1d6c11659c2a3e38b4ef6056778f1d00a2a2` (#3586). Donor: `00b3f410b13ee8731ec8f6b5341c53be176e6a2a` (#3595). Only message_processor.rs and account_processor/bedrock_setup.rs are selected; donor ancestry includes unrelated changes which are not reviewed for transplant. #3594 is excluded.

Candidate two-file `git diff BASE DONOR -- FILES` SHA256: `e30a1c8f2e6ba719cc17f4f1e90f4f5d2a9852906273af05e9cfc1a098b8d8e1`. Worktree was clean at base when inspected; this is not yet a claim about an applied or compiled combination. Manifest records source blobs. No Cargo, vendor request, real credential generation, deployment or security-setting change was performed by reviewer.

## Findings

No routing authorization or experimental-capability bypass found in selected changes. dispatch_initialized_client_request rejects uninitialized sessions and missing experimental capability before dispatch (message_processor.rs:928–942). Protocol definitions retain experimental annotations and account-auth serialization: shared read for discover, exclusive for setup (protocol/common.rs:1225 onward). Both handlers call ensure_bedrock_login_allowed before discovering profiles or validating/setup; this rejects workload identity, externally managed ChatGPT auth, and forced ChatGPT login (account_processor.rs:381 onward). Replacing MethodNotFound with calls is a real integration repair; removing two obsolete dead_code expectations is appropriate.

**Important existing side-effect behavior now reachable:** setup cancels active login before configure_bedrock_provider (base bedrock_setup.rs:131–140). configure_bedrock_provider checks overridden_metadata only after batch_write (bedrock_auth.rs:43–63). batch_write persists edits before computing overridden metadata (config_manager_service.rs:438–448). A higher precedence nested aws.profile or aws.region override, with model_provider not overridden incompatibly, can therefore return an error after changing user config; the preflight only guards model_provider (bedrock_auth.rs:85–99). This is source-confirmed ordering, not a reproduced failure in this review. It does not override the high-precedence policy or bypass auth. Do not claim every rejected setup is mutation-free. A focused public-RPC regression with static credentials, CLI nested override and byte-for-byte config comparison is recommended to make the intended contract explicit. Existing managed-login override tests assert auth preservation, not config preservation.

Discover returns profile names/regions and credential presence/types, not raw secrets. Profile setup invokes AWS SDK credential resolution, so arbitrary profile validation is not guaranteed network-free or process-free. Only static local fixture profiles are appropriate for the authorized checks. Environment setup tests only presence, and source TODO explicitly defers Bedrock ListModels validation. Success is configuration success, not provider authentication/inference acceptance.

## Coverage and review boundary

Existing bedrock_setup suite is registered in tests/suite/v2/mod.rs. Its default initialization enables experimental API. Fixtures redirect AWS profile/credentials files to TempDir and disable EC2 metadata; these are not real provider credentials. Existing three tests exercise discovery/environment setup, profile/environment config and managed-auth priority, and invalid/conflicting credentials. Parent plans to execute only discovery and invalid/conflicting cases to avoid managed auth fixture writing.

Prepared auth-tests.patch independently inspected: both discover and setup with experimentalApi=false require exact -32600/error message; forced ChatGPT policy exercises both endpoints and exact error; config bytes remain equal and auth.json/.env stay absent. The profile payload would otherwise be valid using a static fixture, so the rejection is not confounded by missing credentials. Splitting initialization helper retains the default initialized behavior for existing tests. Pending application/build means these are reviewed test intentions, not passing evidence.

Remaining coverage: no direct workload-identity/external-ChatGPT/uninitialized negative cases specific to these endpoints; nested overriding AWS config rejected-write behavior above; active login cancellation on later write failure; no live Bedrock connection validation. None is supplied by donor CI. Parent build/test logs must be separately bound to final combined source. This review makes no Runtime durability, FinalUse, cross-process recovery or production Bedrock acceptance claim.

## Commands/evidence

Read repository AGENTS.md; inspected git status/rev-parse, exact two-file git diff, protocol routing, AccountRequestProcessor guard, AWS profile discovery/validation, shared config write path and existing/prepared public JSON-RPC tests using rg/sed/nl. No nested AGENTS.md was found under inspected app-server/aws-auth paths; worktree .agents is absent. Source manifest accompanies this report. Final applied candidate and tests require a follow-up hash binding after parent edits stop.

## Disposition

No blocking defect found for the minimal two-file routing repair plus the prepared authorization regression tests. No explicit contract requiring rollback of all Setup errors was identified, so the existing shared-helper post-write error behavior is recorded as an unchanged limitation, not a blocker. No additional production changes are requested. Existing API documentation already describes these declared endpoints; the route repair does not add a new protocol shape.

Reviewed authorization test patch SHA256: `c22de46ac4a79f532afa7beef1eb6341bb70aeb08f7e8701157660f3fceaa366`. Final application and compilation remain pending with the parent; reviewer must rebind the final actual three-file diff if it changes.

## Final applied candidate review

Final `git diff HEAD` independently reviewed: exactly three files, 101 insertions and 29 deletions. Both production file postimages byte-for-byte match donor 00b3f410b13ee8731ec8f6b5341c53be176e6a2a. Test changes match the reviewed authorization patch after formatting. No new blocking finding. Final HEAD remains 74ba1d6c11659c2a3e38b4ef6056778f1d00a2a2.

Actual full diff SHA256: `8dd2132b3d3db7063c94a1d3f9bbb3d519cff429b5b89df00de363d0461eb1d9`. Combined tree: `79abfc839c992f87794b9fa94fc3b81b0f71e4fc`, calculated using a temporary index without modifying the worktree index. Per-file SHA256 values are in the manifest.

Independently inspected baseline-correct-target.log: the two selected baseline cases fail on actual JSON-RPC -32601 “Amazon Bedrock setup is not implemented”; summary 0 passed, 2 failed, 1013 skipped. These establish the missing-route defect on the base, not success of the combination. Parent reports the combined three selected cases are still compiling at this review point. No combined success or strict-Clippy result is claimed here. Final review approval concerns source correctness and bounds, conditional on parent obtaining its required build/test evidence.
