# MEM read freshness and MEM6 archive recovery — 2026-11-10

## Decision and source

**Scientific acceptance: HOLD. Production adoption: false. Action: NoUpdate.**

This follow-up fixes two reproduced Python memory defects and restores the
original MEM6 archive on a second configured host. It adds software validation
and raw-evidence review, not a new successor-task experiment. The 276 historical
MEM6 actor episodes are not rerun or counted again.

- Mechanical format and exact-source workflow stage: [PR #5813](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5813),
  commit `137b8836c77ce95398677846ab122f08e866c5f1`.
- Behavioral repair: [PR #5814](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5814),
  tested commit `4c3b1fb6d40de7c85aedd1964357e138fc7aa9d8`,
  tree `494fe36854e8d26cd9ae0b510e429fe931cef63d`.
- The evidence-only commit containing this report follows that tested source.
  Every receipt retains its original commit identity. No evidence is relabeled
  as a test of a later documentation commit or a merge candidate.

## Repairs and their limits

### Historical snapshot consistency

A snapshot containing a normal generation-one record could be relabeled as
generation zero, rehashed and accepted. The live frontier prevented resurrection
of already-revoked records, but the impossible chronology could contaminate an
old-state intervention.

The store now checks record version against write sequence; validates every
historical record's namespace and sequence against snapshot generation; rejects
duplicate source/key slots; and requires each historical dependency to exist
and precede its dependent. Validation happens before live-frontier filtering.
Seven invalid, rehashed subcases were reproduced on the old implementation;
valid empty and historical snapshots remain accepted.

### Revocation during retrieval

An association callback or another writer could revoke a selected fact after
the initial read. The previous implementation still returned that fact with a
self-consistent receipt. The repair freezes the caller's source allowlist and
rechecks current authority identity, generation, frontier, namespace, path,
selected record bytes and authorized dependency closure after ranking and before
assembling nonempty delivered context. A change aborts the call without a retry.

The final successful authority read is the call's **linearization point**. A
revocation after that read may occur before return or a later external effect.
The effect owner still needs its own commit-time authorization. Any generation
change, including an unrelated write, conservatively aborts delivery. Successful
read timing includes the additional live-view/closure cost; aborted-call and
complete system costs remain unqualified. The receipt v1
schema is unchanged and cannot prove that an older producer ran the new check.

This is a same-authority mechanism repair. It does not establish malicious-owner
rollback resistance, physical deletion of backups or previously delivered
context, independent source authentication, or ordinary Rust owner integration.

## Validation

The exact published source passed **34/34** memory, retrieval and fresh-process
campaign tests locally, with no failures/skips and a clean checkout before and
after execution. The breakdown is 14 store tests, 18 retrieval tests and two
subprocess-campaign tests. New retrieval regressions include a real independent
writer process, update/revoke during ranking, dependency revocation, authority
replacement, namespace changes and caller allowlist mutation.

The original ai395 environment supplies Python 3.12.16, Torch 2.9.1+cpu, NumPy
1.26.4, Pillow 12.0.0 and portable Tesseract 5.5.0. All nine existing MEM workflow
groups passed; they are reported individually in `TEST_RESULTS.json`. The 152
passing observations contain 119 distinct unittest IDs and 33 repeated IDs.
Repeated modules across groups are not independent tests or actor episodes. Torch/OCR tests use real
libraries on synthetic fixtures; they do not establish episodic task benefit.

An additional 14-reader post-update revocation campaign passed on the
byte-identical prepublication tree. Its original commit
`25165442af800067f4417b53df5dd7a55b5d32e5` is retained in the raw evidence.
It used three exited writers and zero model calls; it did not recover a full
owner or fence an external effect.

The first ai395 attempt had 150 passing observations and two OCR failures. Those
fixtures set their OCR library directory from the executable's parent, replacing
the portable runtime's required library path. Only the two failed groups were
rerun, using the already successful MEM5 launcher, whose bytes were checked
before execution. That launcher supplies the original Tesseract library and
language paths. Candidate tests passed 17/17 and MEM6 tests 51/51 with unchanged
source, model and assertions. The seven successful groups were not rerun.

The evidence bundle preserves preliminary failures: abbreviated source identity,
an unreconciled local commit identity, missing local Torch, and the first ai395
OCR environment failure. Successful reruns do not erase those records. Ruff
0.15.13 scoped lint and format checks passed. The canonical `just fmt` completed.
The format stage's eleven Python files have equal before/after ASTs; the exact
workflow identity checks were retained. Required hosted CI is a separate gate;
queued jobs are not passes.

## MEM6 file restoration

The original ai395 archive was copied through the already configured SSH/rsync
channel to `desktop`. Its source immutable version was identical before and
after transfer. The target independently matched all **61,412,948 bytes** and
SHA-256 `f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e`.

The fixed restore verifier, SHA-256
`66abd7fd16340adfc41edaaba5a2a1a16cdd1fdbf2866b50a1e3f95667cee5e4`,
created an exclusive new directory and verified the complete archive, manifest,
object set, every reconstructed file and its disk readback:

| Restored material | Verified count | Verified bytes |
| --- | ---: | ---: |
| Logical files | 10,365 | 243,281,645 |
| Unique CAS objects | 7,122 | 149,046,627 |

Restore job `1a1c6670efe-5074-ff` exited zero with complete durable logs and no
stderr. `RESTORE_RECEIPT.json` records `status=verified` at
`2026-11-10T17:00:17.379823+00:00`. No archived actor/runtime code was executed.

This closes second-host archive verification and fresh-directory **file-byte
recovery** for MEM6. The earlier cloud transfer remains a partial 371/938-chunk
record; full original archive publication to GitHub is not claimed. The original
MEM6 ledger is preserved as a historical checkpoint. Full owner/effect recovery,
independent trust, external runtime/material closure and behavioral recovery
remain open.

### Previously unavailable critical trajectories

A standard-library read-only audit re-read and matched all 224 archived files
for the other retention win, the selector loss and the selector bypass win. It
checked recorded bindings and action/effect chains; it did not execute archived
code or re-score pixels. The frozen evaluator source hash matched the records.

- Retention pair `bd1daa4059274fa7d85d`: observations, OCR and the first two
  actions match. At step 2, bounded retention offers 29 candidates and writes
  the earlier `22.60`; current-only offers and writes the sole current OCR string
  `Tria ea CL Se 7g`. The recorded text scores are 1 and 0.
- Selector loss `f63a25fb9bbcebb0c93c`: both arms write the correct
  `17/06/2018`, preserve committed output and pass pixel verification. The public
  crop covers 0.79545 of the target, below the frozen 0.95 requirement; neural
  covers 0.98016. The recorded failure is insufficient image coverage.
- Selector bypass win `716b97bac5758ef3f2a5`: both arms begin with the correct
  committed date and no image, and neither calls `WRITE_TEXT`. The public image
  quality is 0.53250, above the 0.5 requirement, with adequate coverage; neural
  quality is 0.45965. This is image completion, not newly acquired text memory.

The original partial trajectory audit is retained. This dated follow-up resolves
its three unavailable cases without changing denominators, outcomes or gates.
The full observations, per-file hashes and compact review are in the evidence
bundle's `raw-trajectory-followup/` directory.

## Current scientific result and next executable dependency

The historical [MEM6 result](../../memory-cell-mem6/run-001/RESULTS.md) remains:

| Comparison | Treatment | Comparator | Wins / ties / losses | Interpretation |
| --- | ---: | ---: | --- | --- |
| Fixed-public task working state, 20 source groups | 30/84 | 28/84 | 2 / 82 / 0 | Source-bootstrap lower bound 0.0; gate not met |
| Selector on 14 other source groups | 21/54 | 13/54 | 9 / 44 / 1 | Positive selector replication; one loss and one public bypass remain counted |

Each retention arm includes 16 initial no-ops; initially incorrect cases are
14/68 versus 12/68. Each selector arm includes 10 initial no-ops. These disjoint
experiments cannot be pooled as a memory effect. The source roles are released
development/validation, not an independently authenticated sealed confirmation.

Task working state is implemented and measured. Episodic/source memory has
versioned storage, retrieval and deterministic fresh-process checks. Slow
semantic/skill consolidation remains a separately defined, unimplemented layer.
Existing exact-KV, BM25, chronological ICL and uniform-read-replay fixtures keep
the baseline paths visible, but do not compare real successor-task performance;
the former one-eligible-record cases do not constitute retrieval competition.
No trained association head or model-driven cross-document inference was tested.

[OWNER_PATH_REVIEW.md](OWNER_PATH_REVIEW.md) identifies the actual next dependency:
the native fresh-thread inference path already exists, while Python episodic
records have no implemented import/update/revoke/reconcile bridge into the
original Rust memory owner. The required persistent identity mapping, canonical
source admission and original writer capability cannot be supplied by a local
digest alone. The observed loopback model server was healthy but returned 401
without authentication; no ordinary owner/provider binding was verified.

After that bridge and its original runtime inputs are available, a separately
frozen fresh-session experiment can measure memory on/off, relevant-memory
deletion/replacement, old-state restoration, source changes and the four strong
baselines under matched history and budgets. This report does not relax the
prespecified source-level benefit, correctness, deletion or interference gates.

## Evidence

`EVIDENCE_INDEX.json` identifies the compressed raw validation/recovery bundle
and its complete per-member manifest. `TEST_RESULTS.json`, `BLOCKERS.json` and
`RESTORE_RECEIPT.json` provide the compact machine-readable checkpoint. Original
stdout/stderr, failed attempts, exact commands, source pins, environment versions
and hash-verifiable receipts remain in the bundle.
