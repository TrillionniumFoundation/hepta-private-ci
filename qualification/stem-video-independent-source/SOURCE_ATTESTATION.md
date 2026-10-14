# Publisher-byte video attestation — candidate gate v2

**Research-only, add-only. No independent quality certificate, production authorization, training or model inference.**

## Why

PR #2033 introduced the **v1 identity preflight**. Its inputs were caller-supplied
SHA256 strings: useful for detecting *declared* overlaps but not proof that a
publisher video exists or that its bytes/declared license have been examined.
In particular, six invented hashes could pass the v1 example test. A successful
v1 report **must not** be promoted to verified-source acceptance.

`source_attestation.py` adds **v2 byte-provenanced eligibility** without changing
the old study. It requires an exact GitHub `owner/repo` and immutable Git commit,
fetches that commit's recorded Git tree, rejects truncated/symlink/mismatched
entries, checks the publisher's committed LICENSE and README bytes, downloads
bounded **original** video bytes from the same revision, checks each raw video's
exact Git blob SHA-1 and size, and rejects **all exposed Git blob identities**
even if a different path or a newer source-id formula is supplied, and computes fresh SHA256 byte digests and source
IDs. It then delegates the calculated identities to the existing v1 split and
family-leakage gate. The caller cannot supply its own video SHA256/source ID.

**Scope restriction:** for now the only accepted publisher *claim* is a pinned
`CC0 1.0 Universal` LICENSE, corroborated by a pinned README containing CC0 or
Creative Commons Zero. This is a **publisher declaration**, not a legal
rights determination. Per-file third-party rights, model training contamination,
semantic duplicates, independence of source-group names, audio rights and
non-GitHub sources remain unverified. The tool cannot prove that two camera
source groups represent independent scenes merely from different filenames.
Only prelabel source information is accepted. No model or label is imported.

## Command and exact format

Run the 43 offline tests with no network or model dependencies:

```bash
python3 -m unittest discover -s qualification/stem-video-independent-source -p 'test_*.py' -v
python3 -m py_compile qualification/stem-video-independent-source/*.py
```

For an actual future, **new** six-source CC0 publisher with a verified immutable
commit, create `plan.json` with *exactly* the following structure and real
Git object metadata (placeholder values below MUST be replaced):

```json
{
  "schema": "hepta.independent-video-source-attestation.v1",
  "repository": "publisher/videos",
  "revision": "<40-lowercase-Git-commit-hex>",
  "prior_source_ids": ["<all 12 registered exposed source SHA256 IDs in canonical sorted order>"],
  "license_path": "LICENSE",
  "license_git_blob_sha1": "<40-lowercase-hex>",
  "readme_path": "README.md",
  "readme_git_blob_sha1": "<40-lowercase-hex>",
  "sources": [
    {"path": "videos/original-a.mp4", "git_blob_sha1": "<40-lowercase-hex>",
     "byte_count": 12345, "split": "train", "group_id": "source-a"}
  ]
}
```

Actual plans must have at least **six distinct** video files, at least **two
distinct source groups per split**, no cross-split family overlap and no media
bytes duplicated among candidates. The schematic one-source example **cannot
pass**. For the registered 10 original `360action` videos *plus* two already
examined `shotstack/test-media` clips, the exact externally pinned prior digest
is:

```
b2d6ba8cfededc3894bf3760ec9891cf2be1dbf7fa481ba7e3f7eacf515f60af
```

It is calculated from compact JSON of the **sorted 12 SHA256 source IDs**. The
12 IDs are independently derived from the actual prior experiment's pinned
Git revision, paths and object identities; do not substitute the original
10-item list or hide the CC0 clips in a separate draft branch.

```bash
python3 qualification/stem-video-independent-source/source_attestation.py \
  --plan /approved/prelabel-plan.json \
  --prior-sha256 b2d6ba8cfededc3894bf3760ec9891cf2be1dbf7fa481ba7e3f7eacf515f60af \
  --output /new/attested-source-receipt.json
```

The command makes only bounded GitHub API/raw reads; expected original source
size is at least 1024 bytes and at most 40 MiB each, <=120 MiB total, 6–64
sources. GitHub tree JSON <=2 MiB; license and README <=20 KiB each. It keeps
media in memory only, and **writes no source MP4, frame, audio or weights**.
Receipt output is create-only; no partial successful receipt is written if any
read, SHA, source split or license declaration fails. The receipt contains
source-path/Git blob/original-byte-size/SHA256 identities and explicit limits:
no inferred quality, permission, training efficacy or product eligibility.

## Real-source status as of this study

The independently inspected GitHub tree for
[`shotstack/test-media` pinned at `b790a2b...`](https://github.com/shotstack/test-media/tree/b790a2b72325feecd189291c52663ed8123b1839)
contains five MP4 objects. **Four** of them are rotations/encodings of the
same orientation recording; with the separate captioning clip this provides
only **two distinct recording families**, and both have already been exposed
in earlier research. They are NOT six new video source families, and cannot
constitute a newly qualified train/calibration/heldout cohort. No alternative
media are silently substituted. The local offline tests use explicitly
fabricated byte fixtures to verify the *software protocol*, not independent
external footage or CLIP generalization.

A genuine full acceptance requires a prospectively locked six-plus independent
video candidate cohort from licensed, verified publishers; separate license
review; operator-signed/source-family curation; and **then** model selection and
sealed heldout execution. A finished GitHub Actions job that actually acquires
the video bytes and produces the receipt is needed. CI queued/pending or mock
bytes are not proof of real acquisition.

## Cloud execution

PR CI executes **only** the offline fixture tests. A separately authorized
`workflow_dispatch` can take a prospectively committed plan located at
`qualification/stem-video-independent-source/plans/<safe-name>.json`. This
manual job checks out the exact dispatched commit, performs real bounded raw
GitHub media reads, runs the identical 12-exposed-source gate, then uploads
**metadata only** (`source-receipt.json` + SHA256). A missing plan, missing
source, missing license or unavailable runner is an explicit failure; none
falls back to fake video. Until a complete prospective candidate plan exists,
**do not dispatch the real-source job claiming a successful evaluation.**
