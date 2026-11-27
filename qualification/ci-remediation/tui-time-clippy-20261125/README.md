# TUI time-format Clippy closure

The scoped `just fix` qualification of source
`fac3c71755e688edd7df3c2bd60a5739aeaa2c57` returned 101. Its first compiler
failure was the independently tracked ambiguous `Ok(())` in the app-server
attestation test. Before stopping, Clippy also applied five mechanical changes
across four TUI files. The original controller stopped on the failed command
and changed source; the remaining 17 stages did not execute.

This commit preserves those exact five automatic suggestions. The shared
`Timestamp::format` and `OffsetTimestamp::format` methods already return
`String`, so three redundant conversions are removed. The two direct method
closures become the corresponding function pointers. Date patterns, time
zone conversion, path components, returned text and all assertions remain
unchanged. No allowance or lint setting is added.

The original 73,030-byte command log has SHA256
`a24ade7f131cc03a12ca397f683dc3ef28fc38e9e95a82e909e70d77afec883c`.
The original 2,649-byte automatic diff has SHA256
`c372da52ce7eedcb2776c66767cfb47ca3e686c9fd100747855df667546ffe43`.
The failed qualification and its source difference remain evidence; this
commit does not convert that run into a pass. Local formatting and diff
validation are recorded separately. Scoped Clippy and relevant TUI tests
still require execution on the collected next source cut.
