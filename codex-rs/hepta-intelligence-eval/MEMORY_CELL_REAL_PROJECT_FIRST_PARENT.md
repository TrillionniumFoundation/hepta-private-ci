# Real-project MemoryCell: immutable first-parent byte context

**Research-only, non-promoting source evidence; not a full historical pull
request diff, a sufficient-context judgment, a reference answer or a semantic
citation certification.** No inference, model training or hyperparameter change.

## Why the head-only review packet is insufficient

The existing SHA-pinned public-source cohort fixes **four projects, eight
open pull requests, 80 HEAD file bindings and 16 unsigned questions**.
Their HEAD bytes prove what the source looked like at the declared cutoff.
They do **not** prove what changed, whether a verification gap exists,
whether the recorded PR metadata describes the HEAD, or whether an answer
can be supported by the provided files.

In the frozen manifest **six HEAD commits have one Git parent** (49
HEAD-file references) and **two are merge commits with two parents** (31
HEAD-file references). One of the single-parent PRs includes a **renamed**
file whose previous path is not pinned in the source manifest.
No implementation may silently choose one parent of a merge or guess a
rename source to inflate available before/after evidence.

## Bounded acquisition and independent local re-open

`project_pr_parent_context.py` first independently reopens the
complete original 80-file HEAD corpus through the existing external
manifest pin and exact original SHA-1/SHA-256 checks. It then fetches only
SHA-addressed Git commit/tree/blob objects for the parents declared in that
same frozen manifest. Every downloaded before-file is verified by its
canonical Git blob SHA-1 and written exactly once, without extraction,
code execution, normalization, model inference or generated labels.

The emitted `first-parent/context.json` has **exactly 80 rows** with
explicit categories:

- `byte-different-versus-first-parent`: an exact same-path previous Git
  blob exists, differs from HEAD, and its unchanged bytes are stored in
  `first-parent/before-blobs/`.
- `unchanged-versus-first-parent`: HEAD and its direct parent have
  identical file SHA. **This does not imply the file was unchanged over
  the entire PR.**
- `added-at-first-parent-step` / `added-already-present-in-first-parent`:
  distinguish whether the HEAD path was absent or already present at the
  immediate parent. An `added` status in the PR manifest must not be
  treated as proof of its immediate-parent status.
- `modified-absent-at-first-parent`: a registered HEAD file is not
  available at that exact path in the immediate parent.
- `unresolved-renamed-previous-path` and
  `ambiguous-multi-parent-head`: intentionally **unreviewable from this
  evidence alone**. No invented base tree or original filename.

A second process reopens every `before-blobs` member, rejects non-regular
files, unexpected files, all SHA/census or READY changes, and attempts to
promote unsigned source evidence to reviewer authority. Only a complete,
bounded source audit writes `first-parent/READY.json`. Any rejected
partial acquisition leaves `INCOMPLETE.json` and preserves failure logs.

The source archive is capped at 32 MiB of distinct first-parent bytes
and 512 immutable Git-object requests, and reuses the original
per-blob 1 MiB limit. A first-parent comparison is **not** the
pre-PR base diff; full PR commit ancestry, code-owner decisions,
historical review discussion and patch semantics remain unknown.

## Source-pinned CI and qualified next steps

The existing
`.github/workflows/hepta-memory-real-project-source-bytes.yml` now runs
ten model-free tamper tests, then the old HEAD corpus acquisition and
16-question unsigned review index, followed by this **separate**
first-parent acquisition and independent re-open. The CI retains
original source bytes, before blobs, original source SHA references,
failure/READY receipts, exact Git tested commit, logs and a SHA256SUMS
manifest. A green run is evidence of source-byte integrity, **not**
independent semantic review or a complete PR diff.

After its SHA-pinned artifacts actually complete, an independent owner
can request historical base ancestry and renamed former paths, freeze
those *before* opening any evaluation answer, and obtain human judgments
of source sufficiency and attribution using independent reviewers.
Do not use current mutable PR conversations or a model-generated
explanation as historical ground truth.

**Admission:** `independent_review_performed=false`,
`semantic_citation_precision=null`, `production_accepted=false`.
Neither this archive nor the 16 candidate questions establish unseen
task accuracy or source-family-independent MemoryCell superiority.
