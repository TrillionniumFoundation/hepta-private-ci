# October 12 strict-Reader blinded review handoff: access boundaries

**Research-only worklist, not an independent semantic evaluation.** This
workflow replays the already completed, byte-pinned strict-as-of 576-attempt
six-arm native experiment without loading a model, reading benchmark gold
answers, invoking a new Reader or authorizing production.

## Fixed experiment provenance

- Original run: `38202116864`, completed successfully.
- Generating commit: `d0f69d7b94f65730fa1e093dee6989916f01898e`.
- Generating tree: `87e3b17a0601c17712b9512fc01eadc123060391`.
- Original artifact: `11726530850` in `TrillionniumFoundation/hepta-private-ci`.
- External artifact ZIP SHA-256:
  `07b0f15ec150cc9817db6bfc9b4bae1e2c06a5296ca2ba3c4c7895da18b99e2f`.

The exporter `stem_blind_review_export.py` uses an independent
`PinnedArchive` reader: exact ZIP, complete internal SHA256SUMS, original
source commit/tree, exactly 576 original policy attempts and 32 no-evidence
Reader controls. It builds **32 question cases × two preserved answer
conditions = 64 empty reviewer verdict slots**. Evidence excerpts and
original raw answers are shown only as recorded, without new citation
markers, posthoc target spans or a privileged Oracle.

## Prevent accidental unblinding via Actions artifacts

The earlier workflow uploaded `owner-private/private-owner-case-mapping.json`
as a second GitHub Actions artifact. Calling it `owner-only` did not
establish a separate access-control boundary: users with repository artifact
read permission could potentially open both artifacts.

The replacement workflow uploads **only**:

1. `stem-unreviewed-strict-reader-worklist`: reviewer-visible question,
   evidence and unedited answer snippets plus an *unsigned* verdict form.
2. `stem-blind-review-source-and-tests-only`: exact exporter/test/workflow
   source, original source and tree pins, test logs, receipt and a SHA-256
   checksum of the withheld map — **never the map itself**.

The question/condition identity map is created in a runner-only directory,
hashed for later owner-side reproduction, then deleted before either upload.
The exact-source static workflow regression explicitly rejects adding a
third upload, uploading the owner directory, uploading the entire temporary
root, and including original gold/oracle files. Both artifacts expire after
seven days. An interrupted or failed run must not publish the reviewer
worklist as successful.

To reconstruct the private mapping, the **source owner** (outside an
environment readable by reviewers) retrieves the same byte-pinned original
ZIP and runs:

```bash
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/stem_blind_review_export.py \
  --archive /owner-protected/strict-native-original.zip \
  --output /owner-protected/unreviewed-review-reconstruction
sha256sum /owner-protected/unreviewed-review-reconstruction/private-owner-case-mapping.json
```

The resulting SHA-256 must match `withheld-map-sha256.txt` in the
audit-safe artifact before mapping any externally returned review decisions
back to original questions or conditions. No reviewer credentials are
created or authenticated by the exporter.

## What this still does NOT guarantee

The published native questions and raw historical artifact are separately
available to sufficiently privileged GitHub collaborators. Case IDs are
deterministic, and a reviewer who can access the original benchmark,
repository, or Actions archive could independently recover identities.
**Deleting the direct owner-map artifact prevents accidental release; it
does not provide cryptographic blindness or independent evaluation.**

Actual independent sufficiency assessment must give a different reviewer
read access *only* to the worklist via an owner-operated external channel,
with no access to original gold, input archive, or owner mapping, and must
collect reviewer identity/attestation before any verdict is accepted. A
separate authorized scorer would reconcile reviewer returns under a pinned
manifest and abstain if any required credentials or cases are missing.

The original strict native matrix emitted zero policy citation markers.
There is no meaningful measured citation-precision denominator to call
99% accurate. Review of answer support and evidence sufficiency must not be
misrepresented as a semantic citation precision score. All statuses stay
`production_accepted=false`, `independent_review_certified=false`,
and `scale_out_permitted=false` until new independent evidence exists.
