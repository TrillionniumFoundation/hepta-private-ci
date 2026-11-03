# Synchronous Secret Service encryption selector

This directory retains the official `keyring` 3.6.3 crate. Its archive SHA-256 is
`eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c`.

The added `crypto-rust-sync` feature enables Rust cryptography only on
`dbus-secret-service`. The existing generic `crypto-rust` feature forwards to
both synchronous and asynchronous providers; the synchronous selector avoids
retaining the unmaintained asynchronous zbus family in the resolved graph.
Both production Secret Service connection sites select encrypted DH sessions
with the new feature. It cannot be combined with the asynchronous provider.

The workspace selects `linux-native-sync-persistent` for both of its direct
consumers. Native macOS and Windows stores and the public Entry API are unchanged.
Credential service/account/target attributes and default builder behavior are
retained. In this official release the persistent builder constructs an
`SsCredential`; this patch does not change it into a different cache provider.

The implementation follows the narrow selector introduced in historical commit
`55ad95747cec6d7bf122b1e825eda25fc08f4b36`, re-derived from the checksum-verified
official archive. Historical qualification is not current-source acceptance.
See `qualification/keyring-sync-provider` for new evidence and open boundaries.
