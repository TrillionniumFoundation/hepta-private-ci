# Completion finalization integrity gate

`finalize_preflight.py` verifies retained native V9 CI evidence before calling
the existing, unchanged `qualification/memory-cell-v9/ci_finalize.py`. It never
runs that script itself, tests, training, fix/format, commits or pushes. It
writes a new integrity receipt and returns nonzero on failure. Its own passing
receipt does not assert that any scientific quality gate passed.

## Archive transport v1

Save the exact `INDEX.json`, external `receipt.json`, and contiguous byte slices
of the original `memory-v9-evidence.tar.xz` from the Actions artifact. Do not
recompress each part, rename paths inside the TAR, or delete an unsuccessful
attempt. Each chunk is at most **512000 bytes**; an ordinary choice is 500000.
The following is a specification template, not valid successful evidence:

```json
{
  "schema": "hepta.memory.completion.transport.v1",
  "source": {
    "commit": "<exact-native-tested-40-hex-commit>",
    "tree": "<exact-native-tested-40-hex-tree>",
    "run_id": 40675343830,
    "job_id": 0
  },
  "archive": {
    "path": "memory-v9-evidence.tar.xz",
    "bytes": 0,
    "sha256": "<original-archive-sha256>"
  },
  "index": {"path": "INDEX.json", "bytes": 0, "sha256": "<index-sha256>"},
  "receipt": {"path": "receipt.json", "bytes": 0, "sha256": "<receipt-sha256>"},
  "chunks": [
    {"path": "chunks/000000.part", "offset": 0, "bytes": 0, "sha256": "<chunk-sha256>"}
  ]
}
```

All lengths and IDs must be actual integers; digests are lowercase hex. The
commit/tree are complete 40-character Git IDs. `job_id` must be the actual
positive job ID, not the template zero. All paths are canonical POSIX-relative
names interpreted under the manifest directory. Chunk offsets must cover the
archive exactly, in order, without gaps, overlap or duplicate paths. No complete
reassembled archive is written. The streaming bounds are 8 GiB compressed,
32 GiB expanded, 200000 regular members and a 256 MiB XZ decoder memory limit.

Self-consistent checksums do not authenticate GitHub. Run the separate
`authenticate_ci_artifact.py` gate first, using the origin contract below.
The preflight still records `github_run_authenticated_here: false`; the
authentication receipt is the separate source-provenance result.

## GitHub origin authentication

Retain a separate `GITHUB_ORIGIN.json` beside the transport manifest. This is
a specification template, not a valid artifact identity:

```json
{
  "schema": "hepta.memory.completion.github-origin.v1",
  "repo": "TrillionniumFoundation/hepta-private-ci",
  "artifact_id": 0,
  "zip": {"bytes": 0, "sha256": "<original-GitHub-artifact-ZIP-sha256>"}
}
```

The artifact ID must be positive. Record the ZIP identity of the original
GitHub artifact download, not a repacked ZIP or the nested TAR/XZ identity.
The authenticator obtains run, job and artifact metadata from GitHub and
requires the following independently of the retained manifest:

- The run completed successfully using `.github/workflows/memory-cell-v9.yml`
  with the exact manifest commit and tree.
- The specified `verify` job belongs to that run and commit and completed
  successfully. An unfinished run or a failed upload cannot qualify.
- The artifact is unexpired, belongs to the same run and commit, is named
  `memory-v9-verification-<tested-commit>`, and has GitHub's own ZIP byte count
  and SHA-256 digest equal to the retained origin pin.
- The downloaded original ZIP has that identity and exactly three regular
  members: `INDEX.json`, `receipt.json`, and `memory-v9-evidence.tar.xz`. Every
  member must match the corresponding transport pin. Duplicate names, linked
  or encrypted members, extra paths and unsupported compression are rejected.

Grant the finalization job `actions: read` and `contents: read`. Set `GH_TOKEN`
only on the authentication step, using the workflow's GitHub token; do not set
it at job or workflow scope. API requests disable redirects. The artifact API
must return one HTTPS storage redirect, followed using a separate request and
opener with no Authorization header. Further storage redirects are rejected.
Signed URLs and tokens are neither logged nor written to receipts. The
temporary ZIP is removed after verification, including on failure.

Metadata is limited to 2 MiB per API response; downloads have 30-second socket
timeouts and a ten-minute streaming deadline. ZIP bytes are bounded by the
archive allowance plus 128 MiB. The current three-file ZIP profile also rejects
multi-disk and ZIP64 end directories and bounds the central directory to
64 KiB before allocating the member list. Larger archives require an explicit,
reviewed transport revision. Members are hashed in 64 KiB blocks without
extraction. An authentication failure writes a failed receipt with the failure
stage and exception type; it does not claim a successful CI run.

## What the gate checks

- Every chunk and the concatenated compressed archive match their byte counts
  and SHA-256 identities. A single XZ stream is required; truncation, appended
  compressed data and a nonzero tail after TAR termination are rejected.
- Every regular TAR member matches `INDEX.json`. Symlinks, hardlinks, sparse
  files, special TAR members, duplicate effective member names, absolute paths
  and path traversal are rejected. Colon-containing Unix filenames are retained
  unchanged. Files are hashed as streams and never extracted.
- TAR metadata is restricted to the packer's regular-file/local-PAX profile.
  Each local PAX header is bounded to 1 MiB before its body is read. Nested,
  global, GNU longname and sparse metadata are rejected before their additional
  processing can allocate unbounded buffers. Ordinary PAX long paths remain
  supported.
- `INDEX.json` may record excluded original nonregular entries as metadata
  with `contents_followed: false`. Those paths cannot stand in for a required
  regular file or collide with retained member names; no target is followed.
- `receipt.files` equals the entire native regular-file inventory, excluding
  the CI receipt itself. `ci_verify.py` builds its inventory before writing
  `receipt.json`, so the root receipt is verified separately against its TAR
  copy, transport identity and `FINALIZE_REQUEST` pin. Preparation JSON files
  are additional indexed evidence outside the native receipt's scope.
- Empty files are legal. In particular, `generated.patch` must be exactly
  empty for the clean tested checkout. All eleven required formal raw reports,
  including `fresh-reader/receipt.json`, must be nonempty. Every execution's
  raw command-log identity must match its retained file. Both the ordinary
  ten-package `just test` command and the ignored actual V9 command must have
  completed successfully.
- The successful formal receipt must identify the exact tested commit/tree
  and the `VERIFY_REQUEST.json` at that commit. The original finalizer still
  enforces its remaining package/base, protected-source and fix/format gates.
- `pack_evidence.py` must equal the exact native tested commit's bytes.
  Adapter research has independent provenance: formal-01 `FREEZE.json` and
  `SOURCE_BINDING.json` are checked against current source bytes and their
  original committed blobs. Explicit long-run FREEZE files are checked against
  their own frozen sources, with historical absolute labels rebased only within
  the registered qualification roots.
- The complete current HEAD-tracked adapter inventory, including later docs,
  evaluation/long-run code and retained evidence, is recorded separately.
  Tracked changes, untracked nonignored adapter files and nonregular tracked
  paths are rejected. Git-ignored runtime files are outside this checkout
  freeze. Later adapter additions need not equal the older native tested tree;
  native CI coverage of those additions is never claimed.

The adapter source checks hash held files when they are part of a frozen source
inventory; they do not parse their prompts, evaluate models or retune anything.

## Workflow order

Retain the evidence and the existing `FINALIZE_REQUEST.json` as reviewed,
tracked inputs before triggering finalization. Use full Git history so both
the native tested commit and independent adapter source-origin commit exist.
For the currently retained long-run evidence, the three extra proof paths are:

```text
qualification/memory-cell-adapters/longrun/evidence/longrun64x3/RAW_FREEZE-run-01.json
qualification/memory-cell-adapters/longrun/evidence/longrun64x3/RAW_FREEZE-run-02-resume.json
qualification/memory-cell-adapters/longrun/evidence/longrun64x3-clean/RAW_FREEZE-run-03-clean.json
```

Run authentication with the token confined to that step. Use ordinary separate
steps for the remaining commands, preserving the authentication receipt with
an `always()` artifact-upload step even if authentication fails:

```bash
python3 -B qualification/memory-cell-completion/authenticate_ci_artifact.py \
  --transport <retained-transport-directory>/TRANSPORT.json \
  --origin <retained-transport-directory>/GITHUB_ORIGIN.json \
  --output memory-v9-completion-preflight/GITHUB_AUTHENTICATION.json
```

Run the preflight before creating the old finalizer's output directory:

```bash
python3 -B qualification/memory-cell-completion/finalize_preflight.py \
  --transport <retained-transport-directory>/TRANSPORT.json \
  --request qualification/memory-cell-v9/FINALIZE_REQUEST.json \
  --adapter-freeze qualification/memory-cell-adapters/longrun/evidence/longrun64x3/RAW_FREEZE-run-01.json \
  --adapter-freeze qualification/memory-cell-adapters/longrun/evidence/longrun64x3/RAW_FREEZE-run-02-resume.json \
  --adapter-freeze qualification/memory-cell-adapters/longrun/evidence/longrun64x3-clean/RAW_FREEZE-run-03-clean.json \
  --output memory-v9-completion-preflight/receipt.json

python3 -B qualification/memory-cell-v9/ci_finalize.py

python3 -B qualification/memory-cell-completion/finalize_preflight.py \
  --after memory-v9-completion-preflight/receipt.json \
  --output memory-v9-finalize-output/COMPLETION_FREEZE.json
```

The `--after` operation checks the same HEAD and unchanged adapter/packer
bytes; it is an integrity check, not a post-format test run. Preserve the
authentication and both preflight receipts along with the finalizer's raw
logs, stage patches and final receipt. Do not promote one passing gate into
finalization success if another gate or the old finalizer fails.

The native inventory and source checks are a necessary completion gate. They
do not transform Python residual-cell research into native model integration,
validate a new scientific hypothesis, establish all-system cost superiority,
or replace the actual owner/publication authority checks.

## Local validation

```bash
/tmp/hepta-memory-v8-runtime/venv/bin/python -I -B \
  qualification/memory-cell-completion/finalize_preflight_tests.py -v

/tmp/hepta-memory-v8-runtime/venv/bin/python -I -B \
  qualification/memory-cell-completion/authenticate_ci_artifact_tests.py -v
```

The small fixtures use temporary Git repositories and synthetic receipts whose
research quality is deliberately negative. They exercise corrupt/missing
chunks, corrupt raw members, missing raw reports, duplicate JSON/TAR names,
escaping paths, links, trailers, command-log drift, source mismatch, independent
long-run source proofs, bounded PAX metadata, and changes after the recorded freeze. They do not
produce a receipt for a real CI run. Authentication tests use fixed small ZIPs
and fake HTTP endpoints, covering API/source binding, ZIP and member corruption,
extra/duplicate/escaping/link members, token separation, refused redirects and
secret-free failure receipts. They do not contact GitHub or authenticate any
unfinished real job.
