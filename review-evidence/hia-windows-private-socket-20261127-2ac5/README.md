# Original Windows private socket execution

The qualified source is `2f8ccffc50fe032f036d9b610bb47c89fb8018b4`. This evidence-only child changes no product or test source.

## Actual runs

The original seven-package run for the missing-socket correction at `1543c7d26b0a51b6d5604c29cdf7cc9b21d407db` is run 46012867901, job 140552512071. It completed successfully.

The original seven-package run for the private AF_UNIX endpoint implementation at `2f8ccffc50fe032f036d9b610bb47c89fb8018b4` is run 46015063634, job 140559964783. It completed successfully. Both runs passed all seven Bazel test targets and the final clean-worktree check. No failed run was cancelled or overwritten.

The seven targets are hepta-agentd, hepta-fleet, hepta-intelligence, hepta-memory, hepta-prompt-registry, path-utils, and state. The workflow invokes their complete original unit-test targets. Successful individual test output is not printed by this workflow, so this record claims the actual package-target results and retains no invented individual-test count.

## Product boundaries exercised by the source suite

The Windows endpoint implementation atomically creates a private final parent directory, keeps physical ancestor and parent handles pinned through bind, and refuses insecure existing ACLs without repairing them. It admits an existing leaf only after inspecting its actual AF_UNIX reparse tag, object kind, link count, owner, and DACL. Stale cleanup uses that retained file handle after a second failed connection probe. Ordinary files, directories, unrelated reparse points, unsafe parents, and live listeners remain present when refused.

The added source tests exercise actual bind/connect/rebind, stale cleanup, no-delete-sharing rename refusal, ordinary-file preservation, directory and junction refusal, private ACL revocation, and foreign inherit-only grants. Existing assertions remain in their original package targets.

## Retained evidence

The two gzip files contain the complete unmodified job log bytes; `qualification.json` records both raw and stored hashes. The ZIP is the complete original artifact for the qualified source. Its reported byte count and SHA256 were independently checked after download. It contains the original Bazel compact execution log; the member bytes and SHA256 are also recorded.

The earlier 1543 artifact metadata is retained but this observer did not download that ZIP. The original Mac `just bazel-lock-update` process was still running when this record was made and is not reported as passed here. This component result does not claim that the entire repository has completed its native rewrite or that final branch cleanup is authorized by a test result alone.
