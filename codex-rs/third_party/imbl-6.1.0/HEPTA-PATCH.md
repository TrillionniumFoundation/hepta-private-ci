# imbl 6.1.0 security compatibility patch

Source: official imbl 6.1.0 crate, SHA-256 `0fade8ae6828627ad1fa094a891eccfb25150b383047190a3648d66d06186501`, upstream commit `70ea30037b159c2110bcfc580e0929a1d65acbe1`. The upstream MPL-2.0 license is retained.

Matrix SDK 0.18 and eyeball-im 0.8 require the 6.x API. Upstream 7.0.2 moves to imbl-sized-chunks 0.2.0 and its maintained bitmap module. This patch applies only that dependency/import change to 6.1.0; the collection API and algorithms are unchanged. Both the packaged and original manifests carry the same change. The upstream standalone lock is omitted; the product Cargo lock resolves the actual dependencies.

This removes vulnerable imbl-sized-chunks 0.1.3 (RUSTSEC-2026-0292) and the unmaintained bitmaps dependency from this subtree. No advisory is ignored. Remove the patch when the consuming Matrix/eyeball versions support the patched upstream imbl release.

References: https://github.com/jneem/imbl/blob/v7.0.2/CHANGELOG.md and https://rustsec.org/advisories/RUSTSEC-2026-0292.html.
