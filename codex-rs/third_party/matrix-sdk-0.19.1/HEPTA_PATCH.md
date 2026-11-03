# Matrix SDK 0.19.1 event-context typemap

This package starts from the checksum-verified official 0.19.1 crate. Its Rust
1.96 requirement is retained. The product selects E2E encryption, SQLite and the
AWS-LC Rustls backend explicitly, with upstream default features disabled.

The functional patch replaces abandoned `anymap2` with maintained `anymap3`
1.1.0 in the two manifests and event-handler context aliases. Native context
continues to require Clone + Send + Sync; wasm context continues to require Clone.
No encryption, store, transport or session implementation is changed locally.

The repository formatter applies its normal import/layout conventions to the
vendored Rust files. `qualification/matrix-sdk-019-current/vendor-member-provenance.json`
compares all 209 official files, including an identical formatter replay. The
functional diff after that replay is in `vendor-functional.patch`. Official
archive hashes and source identities are retained alongside it.

Real SDK context extraction, both advisory-triggering crypto APIs, old data-bearing
crypto-store migration, current consumers and isolated Synapse qualification must
pass on the current candidate. Historical branch successes do not qualify it.
