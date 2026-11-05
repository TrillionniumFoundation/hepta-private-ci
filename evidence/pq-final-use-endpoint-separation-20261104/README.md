# PQ FinalUse: distinct clock and frontier paths

Status: **HOLD — bounded configuration fix, not whole-runtime qualification.**

Reviewed runtime input: `5bf9e9eb7dc49ef56caf5143531f3a705fcd0e52` in existing Draft [#4812](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4812). The changed source bytes are identified in [endpoint-source-manifest.json](endpoint-source-manifest.json); the final candidate commit is the immutable Git commit containing this record. The companion Chain continuation reviewed input `44ebe1ae95bd27cfc9eee3a9be27f0e06a084771` in Draft [#688](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/688).

## Problem and resulting behavior

The PQ authorizer already refused reused public keys, issuer/trust path collisions, ancestor symlinks, and a trust path within the rollbackable owner directory. Its clock/frontier path checks did not directly compare those two resolved paths with each other. Different role keys and service IDs could therefore conceal the same configured endpoint path.

`UnixFinalUseAuthorizer::from_pq_config` now refuses equality of the canonical clock and frontier paths before constructing either trust client or creating the local authority directory. The existing path test gains both assignment directions with the original distinct key pins. A new constructor test uses non-service regular files and checks the exact configuration error and absence of the authority directory, so service failure cannot masquerade as the intended refusal. Test assertions use the existing `pretty_assertions` dev dependency.

This enforces the stated configuration constraint. It does not establish distinct administrators, independent key custody, protection against every possible socket alias, or atomicity between a frontier observation and an external provider effect.

## Verification actually completed

| Check | Result |
| --- | --- |
| Original blobs and final two source files | Exact Git blob and SHA-256 identities verified |
| Direct Rust formatter | PASS |
| Repository `just fmt --base 5bf9e9eb7dc49ef56caf5143531f3a705fcd0e52` | PASS, exit 0 |
| `git diff --check` | PASS, exit 0 |
| Host package `just test` | NOT RUN |
| New and expanded native tests | NOT RUN |
| Earlier isolated harness build after executor loss | UNKNOWN / INCOMPLETE |

The repository format run used an independent checkout with the exact input HEAD verified before and after formatting; only the two intended files changed and their handoff hashes remained unchanged. See [repository-format-receipt.json](repository-format-receipt.json).

The initial shared clone failed with exit 128 because traversal encountered a missing promisor object outside the required input tree. That failure is preserved in [repository-format-initial-clone-receipt.json](repository-format-initial-clone-receipt.json). All 12,554 objects needed for the exact input tree were then verified locally, and an isolated repository using object alternates checked out that exact commit successfully. The failure was not reported as a successful format run.

The current environment refuses `socket(AF_UNIX, SOCK_STREAM)` with EPERM; [unix-socket-probe.json](unix-socket-probe.json) is an environment probe, not a native test result. No package acceptance or red/green native execution is inferred from the source checks or formatting.

## Required native continuation

Use an ordinary Linux environment allowing Unix IPC, an exact checkout of this candidate, and the repository test entry point from `codex-rs`:

```bash
just test -p codex-hepta-infer-worker-host
```

Confirm that both of these tests are selected and actually executed:

- `final_use_authorizer::pq::path_tests::ancestor_aliases_are_rejected_before_external_requests_or_owner_open`
- `final_use_authorizer::pq::path_tests::shared_clock_frontier_endpoint_is_rejected_before_service_open`

Ordinary task/payment/CURRENT/FinalUse integration, effect/revocation coordination, full-directory rollback and clone resistance, independent witnesses and the fixed Chain/runtime execution campaign remain separate acceptance work. No activation or whole-chain safety assertion changes.
