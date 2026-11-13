# Actual candidate object and expected inventory addendum

The original graph plan and its derivation remain unchanged. Root subsequently
created candidate commit `0c59aaca0b4932507f068c723f73da2f96729b3d`, with tree
`4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09` and sole parent
`cc57c7198db6293ccca562253c42fffbe2a04633`. This addendum binds that actual object
to expected metadata. It does not report materialization, formatting, compiling,
testing, source-ref publication, or useful task-chain completion.

## Actual object identity

The complete raw commit body was fetched from the existing Git storage blob
`2aa08dc83d297fc37aa7f985afe7af41666d3a98` and checked locally: 731 bytes,
SHA-256 `291212c82bd82e80ff598d1261b1041e467e4e7a31fa6fda13ba9db1bec68623`.
The typed Git commit hash is exactly `0c59aaca0b4932507f068c723f73da2f96729b3d`.
The original body has no final LF. Its tree and parent match the complete graph.
Root separately retained its ten-tree / 1,435 immediate-entry API readback proof
as `816716719793e212b4f7b7208dfb233054c3cf12`.

## Original algorithms and independent anchors

The full inventory shape and serializer come from the original inventory module
`51181866cbbb6e0176aab04117efffa8b6792b31` (22,946 bytes,
SHA-256 `20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2`).
Compact sorted-key JSON with the original final LF reproduces all 5,611,184 bytes
of the existing canonical inventory, including SHA-256
`13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9` and Git
blob `7f94788b70546a8b8030dfd2b9182a7d9287c537`.

The five-field projection function is copied verbatim from original materializer
`972ec74449b113a95b4ec098e562a565f23aa82f`. Only that pure function is executed
in a data-only namespace; neither original module nor its main is run. The
baseline projection exactly reproduces the independently recorded original
3,530,181 bytes, SHA-256
`20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9`, and Git
blob `2def77faf50ba6d74d923732182dcb3cad916e53`.

The new full inventory retains all ten original per-file fields. The native
projection contains exactly `path`, `mode`, `bytes`, `sha256`, and `blob`, sorted
by `os.fsencode(path)`, with the original compact JSON and no final LF. The
complete files are in `expected-inventory-v1/`; its encoding manifest records all
raw, gzip, offset, and part identities.

| Expected artifact | Bytes | SHA-256 | Computed raw Git blob |
|---|---:|---|---|
| Full 5118 inventory | 5,629,701 | `affce692432a4fa61521561e6717a84984f679f3535190b6b88c92cb0f725f44` | `a596ae68859e3263a9ee58e2b5d7334ac9314c34` |
| Native five-field projection | 3,541,985 | `686c516814839ce12a3de6a8907a8efd5f27d4d39d9d4b14e380137698faa1f4` | `68342846200b9ba15f0483d89e28bfcf4c499a44` |

These identities describe complete expected bytes. The archival placement must
be consulted to distinguish actual stored base64-part blobs from computed raw
and gzip identities. No standalone large raw blob is claimed solely because its
hash has been computed.

## Mode preservation and attempt history

All 90 executable rows and the single symlink row are retained exactly from the
canonical inventory. A first local projection attempt incorrectly inferred
symlink permissions from Git mode `120000`, producing zero instead of the
original lstat permissions `511`. The full-row modification-count assertion
rejected that attempt before inventory artifacts were emitted. Its script and
record are preserved. The successor explicitly retains original permissions and
checks the entire 91 special rows for equality; it changes no source bytes.

The separate optional local Git hash process failure (`-11`) is retained in the
original graph review. The final pure Merkle result matches Root's independent
complete Git-index/write-tree calculation. Neither local diagnostic is a native
Rust or qualification result.

## Remaining observation boundary

The candidate inventory requires 15,237 files, 6,788 whole-repository Rust files,
and 6,666 Rust files under `codex-rs/`. These are derived counts, not a new native
filesystem observation. In the expected inventory, `stable: true`,
`matches_index: true`, and an empty status are requirements for a future actual
materialization to establish. They are not evidence that it has happened.

The native author independently derived both expected outputs from the complete
graph, exact 110-path overlay, and original serializers and reported identical
three-part identities. The eventual actual native inventory still must match
the full expected bytes. Real task-chain completion remains zero / Unknown.
