# Final CI retention for head 82402923

Run 44710897181, attempt 1, is completed with failure at head `8240292307116aa4063f7c63d8cdf48a0e8ef773`. The eight selected full job logs identify prospective merge `41efe113b0becba5234af5c0de197c31bb5a4581` as their actual checkout. Final metadata contains all 37 jobs: 19 success, 10 failure, 4 cancelled, and 4 skipped.

Full, untruncated decoded GitHub job responses and their exact log bytes are retained for Linux Clippy, Windows Clippy, Linux GNU tests, Linux musl tests, Mac Intel tests, Linux native Hepta paths, Windows native Hepta paths, and Codespell. Original API responses, earlier watch snapshots, and failed retrieval attempts are retained unchanged. This is not a claim that logs for every one of the 37 jobs were acquired.

Linux and Windows Clippy passed. Mac Intel hepta-agentd unit tests passed in 115.6 seconds; its cognitive qualification target failed in 2.7 seconds. The cognitive suite had two passes and one failure. Its existing fixture minted the next integer-second deadline with only 52 ms remaining; opening the compact executor took place after 263 ms, and the unchanged expiry guard rejected the lease. The failed execution did not reach H7 construction, the intended wait, or the final quarantine assertions. The separately retained exact source review verifies unchanged fixture and relevant lease files across 238, d1d, 824, and merge41.

The four ARM macos-15 jobs were cancelled with `runner_id=0` and no assigned runner name. They supply no ARM execution or pass evidence. Cancellation cause is not established. No cancellation or rerun was requested by this reviewer.

Cargo deny remains a failed job with unknown cause: the retained log retrieval attempt returned `Transport closed`. It was not re-fetched or further diagnosed. Other failed jobs remain failures without additional root-cause claims.

Codespell's retained failure comes from the already diagnosed native5 binary shard. The separate accepted candidate applies the existing skip mechanism to that one exact path with a preceding file-type, length, and SHA guard. This retention changes no workflow or raw artifact.

GNU and musl logs both show hepta unit PASS 89.4 s and cognitive PASS 2.3 s, but may reference the same remote execution; their identical durations are not summed or counted as independent physical runs.

All archive members and every split part were independently read back and SHA-256 checked. Parts are at most 480000 bytes. The archive does not convert engineering CI into model, training, useful-work, adoption, or joint qualification. This work launched no native test, Cargo command, model call, training update, dependency download, host job, workflow rerun, or ref update.
