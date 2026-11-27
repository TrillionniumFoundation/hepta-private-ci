# Preserve failed attempts when Bazel ultimately succeeds

Windows shards 1 and 4 for source
`97ab00451799667faebac2c455a1e3176ebc90cb` completed successfully while
reporting flaky test targets. Their execution-log artifacts contained compact
action records, but no complete failed-attempt test logs. The existing wrapper
only entered its log-copy path when the final Bazel exit status was nonzero.
Console tails therefore do not establish the complete failed-case population.

The wrapper now also archives explicitly reported failed-attempt paths after a
successful invocation when the existing log flag and artifact directory are
enabled. It keeps separate indexed directories and source-path records, removes
duplicate paths after Windows path normalization, and copies the original bytes.
It does not include an unreported final passing log or print an extra console
tail. An invocation without a reported failure does not query or copy test logs.

The original failure path, last 200 console lines, exit status, test command,
retry policy, timeouts, and workflow artifact destination remain unchanged.
Archive-copy errors remain warnings and do not turn a passing test command into
a failure. No additional test or model execution is requested by the wrapper.

The current script suite passes all 90 tests, including three new controls for
successful flaky invocations, successful invocations without failures, and
archive-copy failure. The existing failure-path tests still verify exit code 37,
the 200-line tail, and complete distinct shard/attempt bytes. These are local
wrapper tests, not Bazel or native test qualification. A future normal CI run
must confirm artifact preservation on the new source; this change cannot recover
logs that were omitted from earlier artifacts.
