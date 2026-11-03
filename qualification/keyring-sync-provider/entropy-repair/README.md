# OS entropy repair for the synchronous Secret Service provider

Status: **DRAFT / HOLD for current-source hosted service, Bazel lock and original
platform CI**. The previous `29e41072ce0d097acfd59b5ecc1fdb525e45d75e`
source was rejected after its official dbus-secret-service 4.1.0 provider was
found to use non-cryptographic fastrand for DH private bytes and AES IVs.
`../provider-randomness-hold.json` preserves that finding. Successful old-source
compatibility results remain under `../hosted-29e41072`; they do not qualify
this successor.

## Narrow implementation

The patch retains every official dbus-secret-service 4.1.0 archive member and
restores the OsRng source present in official 4.0.3. Both optional encryption
features select rand 0.8, and the shared IV and DH constructors use OsRng.
All DH arithmetic, AES/HKDF, protocol operations, API, and ZeroizeOnDrop are
retained. Switching the backend or simply downgrading the package would not
preserve all of these properties. No new cryptographic primitive is added.

After applying the repository formatter equally to the official archive and
the candidate, only Cargo.toml, Cargo.toml.orig and src/session.rs differ.
`provider-formatted-functional.patch` is the exact functional diff;
`official-provider-provenance.json` records every official and final member.
Root independently reconstructed and reviewed the final source and optional
feature declarations in `root-independent-entropy-review.json`.

## Locked entropy chain and actual local checks

`cargo metadata --locked --offline --all-features` selects the patched provider
and rand 0.8.6 -> rand_core 0.6.4 -> getrandom 0.2.17. The shared IV helper and DH
constructor both reach OS entropy. The standard Linux fallback waits for kernel
random readiness before reading /dev/urandom. Errors panic through upstream
Rng::fill instead of substituting a weak source. This preserves the older
upstream failure behavior, not a new recoverable error API. Exact source and
resolved-edge hashes are in `entropy-call-chain.json`.

The final Cargo lock changes only the provider record; its other 1,499 parsed
package records are unchanged. The existing two Windows dependency edges were
retained after the scoped resolver initially selected different already-locked
versions; the final complete lock passed the original locked metadata command.

- Original `just test -p codex-secrets --locked --offline --no-tests=fail --retries 0`:
  **15 passed, zero skipped**, 20.206 seconds; all production inputs unchanged.
- Original scoped `just fix -p codex-keyring-store --lib --locked --offline`:
  actually checked the patched provider and wrapper, **exit 0**, inputs unchanged.
- Same original deny policy and RustSec DB
  `6c5fedf8ff03c485ed674d8f941e0180f3f72d70`: **four remaining advisory errors**,
  RUSTSEC-2024-0449 and RUSTSEC-2026-0318/0319/0387. Bans, licenses and sources
  each have zero errors. Full output is losslessly compressed with both hashes.

The local environment's original C identity failure and D-Bus socket restriction
are still retained in the parent directory. They were not patched around.
The native fixture on the hosted runner reruns the actual old/new wrapper
credential exchange against a private real GNOME Secret Service, including
restart recovery and rejected DH with no plaintext retry. The candidate probe
explicitly patches this same provider and snapshots all its files.

## Required next verification

The source branch workflow regenerates MODULE.bazel.lock using the unchanged
`just bazel-lock-update`, runs the original lock check, native C identity test,
and real keyring-store Bazel target. Its generated lock must be adopted and
verified against this exact source before claiming synchronization. Full
required platform CI remains independent. No ignore, allowlist, credential
format, test assertion, native identity condition, or supported format is
relaxed by this change.
