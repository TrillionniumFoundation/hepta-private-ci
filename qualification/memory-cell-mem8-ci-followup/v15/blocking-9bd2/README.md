# Original 9bd2 blocking CI terminal evidence

This freezes the original `43021840778` attempt 1 at source
`9bd2f589debdba4a93baa363817c3669cb103721`, tree
`c77785ecb368c44ea699769001a47402c9f50591`. The actual Bazel merge checkout is
`8644d1044c50c7d4bfa47834f2602d133433300d`, with the same tree. The original run
finished in failure: 37 terminal jobs, 19 success, 9 failure, 5 cancelled, 4 skipped.

The unmodified earlier 38-member checkpoint is embedded as a complete tar. It
contains all twelve full decoded job logs already retrieved at that time, exact
source files, raw failure-block audits and GNU/musl byte-dedup proof. Its earlier
Mac-pending snapshot remains an earlier observation; the new terminal run/jobs
metadata and summary provide the later state without rewriting it. Its original
offline-verifier instrumentation error and documented delimiter correction are
retained. A thirteenth complete decoded log records the final CI-required job.

Mac Intel job `130526871572` completed in failure at 13:58:22 UTC. Its original
test step ended in failure at 13:57:09. The full job log was not received: two
read-only GitHub log-tool calls returned `Transport closed`, and the precise GET
fallback was rejected as an unsupported tool endpoint. All three agent responses and the root's independent Transport-closed response are
preserved. This is a retrieval gap; it does not mean zero tests, a native timeout,
or a diagnosed failure cause. The complete original execution artifact
`13861597870` is included: 10,562,035-byte ZIP, CRC and API SHA verified, containing
one compact `.zst` execution-log member. No decoder or missing stdout is invented.
That artifact does not substitute for the missing test stdout and assertions.

The original CI-required job `130567945859` receives `abandoned` for the Bazel and
repo-checks workflow dependencies and failure for blob-size-policy, and rejects
`invalid or absent CI result: bazel`. This is preserved as fan-in behavior, not
counted as an additional native test. No gate is weakened.

All actual original automatic attempts, flaky outcomes, failed assertions and
cancelled/unexecuted jobs retain their identities. Bazel target totals are not
native case totals. Identical GNU/musl failure payloads are not counted as separate
physical replications. Neither staged source repairs nor later V6 source-only
passes overwrite these results. Private-state, Windows-current, MEM and
Architecture runs have separate packages and are not combined into this run.

Run `python verify_terminal_package.py <extracted-directory>` for a read-only
replay of every outer hash, the original checkpoint verifier, all 37 terminal
metadata identities, the final fan-in raw text, and the complete Mac execution
artifact. This starts no repository tests, compiler, host service, CI run or model.
