# Restore upstream operating-system randomness

This directory retains the official `dbus-secret-service` 4.1.0 crate,
SHA-256 `708b509edf7889e53d7efb0ffadd994cc6c2345ccb62f55cfd6b0682165e4fa6`.
The narrow patch restores the operating-system random source used by official
4.0.3, SHA-256
`b42a16374481d92aed73ae45b1f120207d8e71d24fb89f357fadbd8f946fd84b`.

Official 4.1.0 uses `fastrand::Rng` to generate the shared DH private key bytes
and the AES IV used by both encryption backends. `fastrand` explicitly does not
provide cryptographic randomness. Both optional encryption feature declarations
now select `rand` 0.8, and both random-source constructors use `OsRng` as in
4.0.3. The DH arithmetic, AES/HKDF implementation, wire protocol, API, and 4.1.0
`ZeroizeOnDrop` behavior are retained. No new cryptographic primitive is added.

The locked `rand` 0.8.6 re-exports `rand_core` 0.6.4 `OsRng`, which calls
`getrandom` 0.2.17. On Linux this obtains kernel entropy; on older kernels its
file fallback waits for the kernel random generator to be ready. An entropy
failure aborts the operation through the upstream `Rng::fill` panic, with no
weak random-source fallback. This preserves the upstream 4.0.3 error behavior;
it does not add a recoverable entropy-error API.

The archive's own `Cargo.lock` is provenance only. The workspace lock and the
isolated qualification consumers select the patched package explicitly.
See `qualification/keyring-sync-provider/entropy-repair` for exact input hashes,
the functional diff, actual checks, and remaining acceptance boundaries.
