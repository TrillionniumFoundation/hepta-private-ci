# Round 8 evidence transport correction

The original blob-size job on PR head
`682a88a7f847e31ffb6cd5e0a630dd71dde4bfee` failed because the downloaded artifact
ZIP is 1,270,736 bytes, above the unchanged 512,000-byte limit. This follow-up
removes that ZIP from the current tree and keeps a verifiable external reference.
The original artifact, native outputs, dependency files, and earlier failure
records are unchanged. No policy, allowlist, workflow, feature, or advisory
setting is modified.

## Obtain and verify the original bytes

- [Original artifact download API](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/12791038108/zip)
- [Original proposal run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40630710054)
- [Historical committed ZIP](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/682a88a7f847e31ffb6cd5e0a630dd71dde4bfee/qa/pon-dependency-resolution-20261028-r8/artifact-12791038108.zip)
- Original ZIP SHA-256: `7cb5ad030c5d63ae3dce23cc35a6aeb05d6882571b096ef724afc5a66649f330`
- Original ZIP bytes: `1270736`
- Historical Git blob: `9899846396fef57c538c9964732eda1afec5ad2e`

The coordinator has retained the exact original at
`recovery/round8/hepta-pon-dependency-proposal-r8.zip` outside the repository.
The Actions artifact has its original retention policy and may expire; the
historical commit/blob and the coordinator's archive are separate recovery
sources. Access to these private-repository URLs still requires the original
repository authorization. This change neither uploads credentials nor changes
access permissions.

Run the retained graph verifier with the original ZIP as an explicit input:

```sh
python3 -B qa/pon-dependency-resolution-20261028-r8/verify_resolution.py \
  --artifact-zip /absolute/path/to/artifact-12791038108.zip
```

The verifier fails if the input is absent, a symlink, incorrectly sized, or has
the wrong SHA-256. After that check it executes the same 23-member, manifest,
source, Cargo graph, Bazel graph and feature review. A missing archive is an
error, never a successful skip.

## Complete member and container identity

`artifact-12791038108-zip-envelope.json` preserves all 23 member names in central
directory order, their sizes, SHA-256 hashes, CRCs, compression settings, flags,
attributes, timestamps and ZIP extras/comments. It also retains the exact local
header bytes, data descriptors/gaps, preamble, central directory and end records
as hex. Each original compressed stream has a size, offset and SHA-256. Together
these describe every byte interval of the original ZIP, while the external ZIP
remains the authority for its actual compressed streams and member payloads.

No metadata-only file is presented as a substitute for the full raw logs. The
complete payload is 12,634,631 bytes, including the 8,254,348-byte Cargo metadata
stream. The original internal `files.json` still covers its other 22 members.

Before selecting references, a lossless single `tar.xz` archive was generated
with all 23 exact member payloads plus the ZIP envelope metadata. It measured
668,848 bytes with SHA-256
`806dcaa58afa6708ccf2f6feebf0812ba48ba5536c5d690749c7f0142af7c6d1`, still above
the cap. That failed candidate is recorded and is not checked in. The artifact
was not divided into pieces, and no exception was added to the size policy.

## Historical failures remain visible

The `d9dfaa9` / `682a88a7` candidate manifest, import review and original local
verification logs remain historical receipts for that exact tree. Their ZIP
entry has not been rewritten to imply that the original gate passed.
`transport-readback.json` records the raw original blob-size log identity and
the actual failure. It also records the subsequent original cargo-deny finding:
four targeted advisory errors disappeared, while `RUSTSEC-2026-0387` on
`crypto-bigint 0.5.5` still fails. This transport change does not close that
separate dependency blocker or qualify native behavior.

`local-verification.json` describes the checks actually performed for this
follow-up. They use only Python, JavaScript formatting and read-only Git access;
no local Cargo, Rust, Bazel, build or native test was run.
