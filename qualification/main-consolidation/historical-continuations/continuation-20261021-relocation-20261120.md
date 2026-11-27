# Continuation checkpoint relocation

This record describes the location of a sealed historical checkpoint. It does
not renew the checkpoint, change its observations, or claim that current tests
have passed.

The original directory is `qualification/continuation-20261021`. Its complete
Git tree is preserved at `qualification/main-consolidation/historical-continuations/continuation-20261021`.
The original README remains inside the preserved tree; a new README at the old
location links here.

| Recorded identity | Value |
| --- | --- |
| Original repository commit | `0cee57ca617e0324e2df8e9447a2c075a6c76952` |
| Unchanged subtree | `d7840f4325fa2f5312a937084bb648a3c42a3d1a` |
| Original manifest blob | `03b03a82a251aa50be39aa3f117a6cb32a1fc007` |
| Original manifest SHA-256 | `416c48d29d1f5359ee154b3e491f98fe43301942abc3e7e2bb3679f4d13b12b3` |
| Original seal time | `2026-10-21T02:04:57.512454+00:00` |
| Payload files described by the manifest | 263 |
| Payload bytes described by the manifest | 9,740,822 |
| Files in the complete tree, including MANIFEST.json | 264 |
| Bytes in the complete tree | 9,810,878 |

Every file retains its original mode and Git blob. The manifest retains its
original bytes, including the historical directory field and source identities.
Relative references inside the checkpoint remain historical records; this move
does not claim that references outside the checkpoint are self-contained.

Three existing spelling custody entries follow the relocation with unchanged
SHA-256 values. Two original C52 audit JSON records remain at their current
paths and retain their exact bytes; their exact paths and hashes are registered
through the existing custody checks. No general spelling rule, dictionary,
workflow check, or verifier predicate changes.

Four historical Rust files move inside this tree. They are outside the active
`codex-rs` workspace and are not new Rust execution results. Their path change
must be recorded separately when binding a source inventory.
