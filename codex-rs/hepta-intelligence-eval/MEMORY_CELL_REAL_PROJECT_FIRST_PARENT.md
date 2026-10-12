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

## Independent SHA-addressed initial feasibility observation (Oct 12)

Before the new 80-file hosted artifact completes, the immutable parent
object IDs in the published source manifest were checked directly using
GitHub's SHA-addressed Git endpoints. **All ten registered parent commit
object IDs were retrievable and matched the declared SHA.** This is
source-object availability only; it is not an independently verified
human judgment or GitHub-hosted READY certificate.

Six single-parent HEAD commits were compared with their declared parent
commit SHAs, never a moving branch or historical PR description:

| Project | PR | Frozen HEAD-file references | Paths changed from immediate parent |
| --- | ---: | ---: | ---: |
| rust-lang/rust | 164037 | 2 | 2 |
| rust-lang/rust | 162467 | 8 | 7 |
| kubernetes/kubernetes | 142136 | 2 | 2 |
| kubernetes/kubernetes | 142932 | 20 | 2 |
| numpy/numpy | 32910 | 3 | 1 |
| astral-sh/ruff | 29127 | 14 | 14 |
| **Total** | | **49** | **28** |

The remaining **21 of 49 HEAD-file references** were not changed by
their immediately preceding commit, although some may have changed in
earlier PR commits. The Rust 162467 first-parent comparison contains
**12** changed paths, while only **8** are in the original frozen
source manifest: the other four must **not** be silently added to the
preregistered 80-file/16-question evaluation cohort.

Two multi-parent HEADs — NumPy 32523 (26 frozen file references) and
Ruff 28828 (5) — remain explicitly unresolved as unique-parent
comparisons. The rename in Rust 162467 reports a former path through
the immutable commit comparison, but the original frozen source cut did
not predeclare that former path; do not treat this late observation as
the source-verified prior blob until independently rebound and audited.

These endpoint-level observations are **not** a complete saved binary
diff, CI pass, or model answer. The new hosted workflow must still
verify original and first-parent blob bytes and independent disk re-open
against its exact running source commit. A failed hosted gate must
remain FAILED and retain its INCOMPLETE output.

## Two-parent concordance sidecar (source-only)

The supplementary \`project_pr_merge_concordance.py\` compares the two
immutable, frozen parent trees for the **31** original HEAD file references
belonging to NumPy #32523 and Ruff #28828. The original 80-file archive and
first-parent receipts remain unchanged; the previously unresolved 31 cases
are **not retroactively relabelled** in the historical first-parent report.

The sidecar admits a common previous version only when **both registered
parents** resolve the **same regular Git blob and file mode at the same path**.
If both match HEAD, no new blob is copied. If both agree but differ from HEAD,
the exact prior Git bytes are fetched, verified against Git blob SHA-1 and
SHA-256, and stored under a separate 24 MiB bound. A divergent parent pair,
a missing path on either side, or a rename remains explicit unavailable
context. This is not a unique merge-base or a complete PR-level diff.

The existing read-only source-byte workflow checks six fixture regressions,
verifies formatting, acquires original/first-parent bytes, runs the bounded
two-parent comparison, and reopens all retained bytes in another process.
Incomplete acquisition leaves an INCOMPLETE marker rather than READY.
Its original code, question and review manifests remain answer-blind; the
new record contains no user gold, no generated model answer, no human vote
and no qualification. Zero or any number of common-parent matches cannot
by themselves establish a new task success or independent reviewer consensus.

The resulting \`merge-concordance/READY.json\`, \`concordance.json\`,
\`common-previous/*.blob\`, original source, complete hashes and failure logs
are research material for a **future independent sufficiency reviewer**.
Do not use these source-only observations to update candidate weights,
choose evaluation cases, assert >=99% entailment or ship a production Cell.
The live CI run must finish before citing a measured resolved count.
