# Exact linked V8 sandbox variants

Source leaf `ec392d3067809cbc4c1728a53bc0c48d4a7f7347` accounts for Cargo's additive
dependency features. A requested sandbox still requires a true linked FFI flag.
The two supplier workflows explicitly provide `RUSTY_V8_EXPECT_SANDBOX` so each
staged true/false artifact must match its exact variant. The product code-mode
assertion requiring sandbox=true is unchanged.

The [publication manifest](publication.json) preserves the failed original
feature-unification case, all76 original owning-package passes, six actual
tests with each official Linux/x86_64 archive/binding pair, and both deliberately
wrong expectations rejected by the original FFI assertion (exit100). All19
original Python workflow tests passed. Artifact postflight digests match the
recorded official150.4.0 release metadata. This did not rebuild supplier source.

The tested patch and final patch hashes are equal. Scoped fix/fmt succeeded
afterwards without another same-phase test. These are Rust1.95 Linux functional
results; final Rust1.96 workspace, remote-platform and native qualification remain
separate. Compressed logs round-trip byte-for-byte according to the manifest.
