# ZIP 9.0.0 feature isolation

This directory preserves the published `zip` 9.0.0 package. Its archive SHA256
is `711e8c9646791c49b7eb799a19c4ae70a9b8372ddc6a1fa4778defd1e2aa5d5e`.
`VENDOR_PROVENANCE.json` records every original file and the exact two changes.
All upstream Rust runtime source and the MIT license are unchanged.

The upstream `bzip2-rs` feature includes `dep:bzip2` and
`bzip2/bzip2-sys`. Cargo's strong dependency-feature forwarding also activates
the explicit feature named `bzip2`; that feature enables `bzip2/default` and
pulls in `libbz2-rs-sys`, even though the C FFI is selected for actual use.
Real Cargo metadata and native compilation expose this dependency, while
cargo-deny 0.19.0's reconstructed graph omits it. A successful license listing
alone therefore did not establish the intended dependency isolation.

An intermediate weak edge, `bzip2?/bzip2-sys`, fixes Cargo's unwanted backend
activation, but cargo-deny 0.19.0 then also omits the active C backend from its
license graph. The retained experiment records this failure; it is not the
adopted patch.

Both manifests instead declare `features = ["bzip2-sys"]` directly on the
optional, default-disabled bzip2 dependency. `bzip2-rs` activates that dependency
without forwarding another feature. This fork selects the application's
existing C backend whenever bzip2 is used; it does not claim to preserve an
independent Rust-only backend selection for other upstream feature profiles.
The application's explicit feature configuration preserves all eight selected
ZIP capabilities, including Bzip2 and AES. No license or advisory policy is
changed, and neither compression implementation source nor archive behavior
is rewritten.

The Bazel library mirrors the actual resolved ZIP feature set and includes its
README for compile-time documentation. The registry package deliberately omits
upstream test data; it remains a dependency library rather than introducing
unrunnable upstream unit targets. Existing core-plugins extraction regressions
continue to cover actual product behavior.

Reproduce the dependency check from the repository root with the pinned Cargo:

```bash
python scripts/check-zip-feature-isolation.py --offline --check-deny
```

The check invokes real locked Cargo metadata, verifies the C backend remains
active, and rejects an active `libbz2-rs-sys` dependency. It also checks that
the Bazel library feature selection agrees with Cargo's resolved ZIP features.
`--check-deny` also executes cargo-deny and rejects a missing or extra ZIP/bzip2
package in its license listing. It does not claim full native, Bazel, or
workspace CI qualification.
