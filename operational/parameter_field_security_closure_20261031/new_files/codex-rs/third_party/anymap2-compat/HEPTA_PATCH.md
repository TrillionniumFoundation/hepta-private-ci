# Maintained type-map implementation

This local, unpublished facade replaces the retired `anymap2` implementation
with crates.io `anymap3` 1.1.0. Its registry archive SHA-256 is
`fb5dfbc6d8d2675589ccbe4d0fd61df2419075625f8c1a62325e718e2b0049f9`.
No source from the retired implementation is included.

Matrix SDK 0.18 uses `Map<dyn CloneAnySendSync + Send + Sync>` on native
platforms and `Map<dyn CloneAny>` on wasm. Maintained anymap3 directly supports
both trait-object forms; the old trait names are aliases only. Ordinary `Any`
continues to mean `core::any::Any`, so non-cloneable values remain supported.
The source and tests are reviewed as an application compatibility facade, not
represented as an upstream anymap2 release.

