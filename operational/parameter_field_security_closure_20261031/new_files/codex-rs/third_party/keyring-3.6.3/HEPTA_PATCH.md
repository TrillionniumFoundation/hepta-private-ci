# Keyring 3.6.3: maintained Secret Service transport

The published crate archive is unchanged except for its two manifests:
`keyring-3.6.3.crate`, SHA-256
`eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c`.
The MIT and Apache license files and all Rust source are retained.

The optional Secret Service and zbus dependencies advance from major 4 to the
explicitly vendored Secret Service 6 compatibility backport and published zbus 6.
The `async-io` feature selects zbus 6's renamed `default-rt` feature; `tokio`
continues to select `zbus/tokio`. No feature names are removed. The existing
`linux-native-async-persistent` combination retains both Linux keyutils and
Secret Service persistence. Apple, Windows, BSD, cryptographic negotiation,
service/account/target selection, credential builders, and product source remain
unchanged.

Keyring 3 uses the preserved Secret Service blocking API. This deliberately
avoids importing a keyring 4 migration or replacing the Linux persistent native
backend. Historical keyring 4 qualification does not establish this candidate's
compatibility; current resolver, compiler and native interoperability evidence
must be evaluated for these exact source bytes.

