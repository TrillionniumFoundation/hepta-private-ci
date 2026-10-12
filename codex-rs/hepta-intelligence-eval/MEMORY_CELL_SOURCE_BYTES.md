# MemoryCell original source bytes: next untrusted evidence boundary

This continuation **does not** generate gold answers, attest to independent
review, run a reader, train an adapter, certify original PR discussions, or
qualify production. The existing fixed 2026-10-12T09:45:00Z four-project,
eight-PR, 80-file metadata cut is the sole source of object identities.

`project_pr_source_materialize.py` resolves each frozen HEAD Git commit and
checks its exact tree and parent identities. It then walks pinned trees by
path; executable regular-file modes are allowed but symlinks and Gitlinks
are rejected. The actual file bytes must agree with the declared Git blob
SHA-1, and are independently SHA-256 fingerprinted into a bounded artifact.
It never looks up a moving branch, issue discussion, current PR head or
runtime answer. No model executes and no text is treated as instructions.

Research resource limits: 1 MiB per Git blob, 24 MiB total unique source
bytes, 512 original Git object GETs (cached), 6 MiB per Git tree reply,
35 minute hosted job. All 80 file bindings across eight PRs must succeed to
publish `READY.json`. A network/rate-limit, invalid original path, changed
parent/tree SHA, symlink, oversized file, bogus Base64 or SHA mismatch writes
`INCOMPLETE.json` instead of a fictitious usable corpus. Partially received
bytes are diagnostic evidence only and cannot enter a downstream reader.

The output stores original file blobs keyed by SHA-1 and an inventory recording
PR identity, original path, exact tree, original content SHA-1 and additional
SHA-256; it does not include annotations, evaluation labels or reviewer
verdicts. This authenticates what the frozen Git trees say at those commits,
not whether those blobs alone are sufficient context for future questions.
A qualified independent reviewer must separately certify sufficiency and
blind answer labels. Four projects with two PRs each do not meet N_eff>=200,
real prospective windows or production authority.

Local test command:

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_project_pr_source_materialize.py' -v
```

Hosted source acquisition:
`.github/workflows/hepta-memory-real-project-source-bytes.yml`.
Original pre-review source cut remains unchanged and external SHA256-pinned.
These tests contain synthetic Git objects only. All existing Architecture,
blocking CI, performance and independent acceptance gates remain in force.
