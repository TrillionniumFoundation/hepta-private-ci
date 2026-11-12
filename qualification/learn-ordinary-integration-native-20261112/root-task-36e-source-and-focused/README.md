# Complete source QA and focused caller observations at 36e9cb98

Both runs observed the same clean local candidate `36e9cb98b1d56ba38d99c6ae3b1010d74584381c`, tree `e3e4d96eddfcc00b4227f22861efef98798686e4`. The before/after 7,461-file inventory is unchanged with SHA-256 `1e85cae7b32bb85255236a22cfd9dde5d8d1fb6675e5838a078b337bfe1b1b6f`.

Full `qa/b4-no-bypass/*source_closure.py` discovery passed all 299 tests and exited 0. The exact 63,687-byte log is preserved with SHA-256 `539a76aca18ec72c6730d612ff7756a35eb7d3ca7cb92ed15a7ca5b408cc47ce`.

The independent **focused** caller run indexed 6,580 Rust files and selected 85 boundaries. It passed 84 and failed one: `root_original_ledger_historical_observation` could not resolve the possible `PendingOriginalLedgerHistoryV1::observe_original_terminal` receiver in `authority_host_historical_ledger_pin.rs`. The run separately checked all 491 protected-file rows and the 629-entry privileged inventory. It was not a complete all-boundary caller run. The exact 33,111-byte log has SHA-256 `79d7ef839bb04b3735dcb30f7ffe4a544b9d9f7310170d2bff108c262284563a`.

The four complete original files were compressed and verified byte-for-byte after decompression. The earlier d454997a failed source-QA record remains in the adjacent qualification directory. Later explicit receiver repairs require a new source identity; this passing source QA does not qualify those later edits.

Neither scope executed native tests. Complete A-to-C positive, NoUpdate and daemon-plus-Root cold-restart counts remain 0 / 0 / 0.
