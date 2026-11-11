# Independent C2 original-state recovery observation

This appendix follows #5920 at `4ed61beacd9e8cf08cd1f7f8c938b75d747149e4`.
The fresh original-fit observation is from 2026-11-11 04:53:58 UTC. It does
not replace the original missing controller terminal, repair original logs,
restart training, or grant numerical or scientific admission.

## Verified result

The independent read-only checkpoint audit verifies 639 bound original files
(67,151,813 bytes) before and after its checks. All six retained last/best
checkpoint pairs deserialize with `weights_only=True`; their model structure,
frozen parameters, AdamW step ages and RNG state pass the original structural
validator. All 289 immutable C2 epoch commits form the expected chains, and
their complete epoch rows match the original event journals.

The four existing producer results are reconciled against the immutable commits
and original stopping rule: at least 30 epochs, patience 10, and plateau delta
0.002. Their first plateau epochs are 116, 76, 50 and 72. Independent calculations
from the retained full-development logits reproduce the accuracy, macro-F1,
negative log likelihood and Brier score exactly. The separate independent model
forward replay also completes on all four
retained best checkpoints: each traverses all 128 development episodes and
31,952 labeled events, reproducing every saved logit bitwise (maximum absolute
error 0). Its full stdout, result and process receipts are retained. This is
reproducibility on the original development set; no independent held-out E
confirmation is claimed.

| Fit | Last epoch | Strict best epoch | DEV macro-F1 | Original terminal |
| --- | ---: | ---: | ---: | --- |
| s101, lr 0.001 | 116 | 106 | 0.344016998 | Reconciled |
| s101, lr 0.003 | 76 | 74 | 0.387834260 | Reconciled |
| s211, lr 0.001 | 126 | 124 | 0.377902993 | Missing |
| s211, lr 0.003 | 50 | 40 | 0.391093236 | Reconciled |
| s307, lr 0.001 | 127 | 126 | 0.332319078 | Missing |
| s307, lr 0.003 | 72 | 62 | 0.349830589 | Reconciled |

The two scores with missing terminals come from the retained complete-epoch
history. They are not independent terminal-evaluation results. Their stale-epoch
counts are only 2 and 1; neither retained history reaches the prescribed plateau.

## Preserved incomplete evidence

The original controller job `1a1c74f3308-be2a-75` remains `finalizing`, with
unknown outcome and no authoritative terminal publication. Controller
`RESULT.json` is absent. Its 28,672-byte journal still has the original SHA-256
`1405bced8c59a294276616cd7054f2b4068e10d858ab61d78bb578b93992239f`, with 16
complete JSON rows and a torn 17th.

For s211/lr0.001 and s307/lr0.001, both `interrupted.pt` and
`development_logits.pt` are zero bytes. Their event journals have torn final
rows at lines 3075 and 3114. The valid prefixes contain 10 and 11 completed
updates beyond their last complete epoch; s211 also has an unclosed
`optimizer_started` record. No unknown update or cost is silently discarded.

Audit v1 intentionally retained its failure on the first torn journal. Audit v2
accepts only the complete prefix for inspection, records the torn tail, and
retains the missing-terminal result. It does not turn prefix validation into
resume authorization or a reconstructed original terminal receipt.

## Runtime and costs

The audit uses the original Python 3.12.3 / Torch 2.8.0+cu128 runtime on desktop,
and verifies the complete original runtime identity. It performs no optimizer
steps. This runtime is separate from any newer Torch installation used for
the current CI or P1 numerical qualification.

The four-checkpoint model replay reports 506.567670 seconds of process wall
time as a lower bound through report creation, 502.387291 seconds of CPU, and
1,030,684,672 bytes peak RSS, using one CPU thread. Its 635 bound inputs remain
unchanged. No optimizer update or held-out confirmation access occurs.

The successful checkpoint audit reports 8.853479 seconds of process wall time
as a lower bound through report creation, 7.112813 seconds of CPU, and
671,121,408 bytes peak RSS. Energy was not measured. The failed v1 attempt is
retained and is not charged as zero. Four original C2 per-child `wait4` receipts
are retained; the other two final process costs and the entire original campaign
cost remain incomplete.

## Original selected-state archive

The complete 4,368,037-byte selected-state ZIP is now included under
`original-selected-state/` as ten SHA-256-bound parts, each no larger than
450,000 bytes. The [part manifest](original-selected-state/ARCHIVE-PARTS.json)
records their assembly order and the complete archive SHA-256:
`a1f624d88b3e240b3e583987210a1422c47cbab92ecd59beee5a1c6b28b2d92b`.
No blob-size policy was relaxed.

The ZIP contains **368 original source members plus one embedded manifest,
for 369 ZIP entries**. The original source members total 16,003,349 bytes;
the embedded manifest adds 75,210 bytes, making the total uncompressed ZIP
size 16,078,559 bytes. It preserves four completed fit best checkpoints, two
incomplete fit last checkpoints, all 289 small immutable epoch commit records,
producer results, original torn journals, zero-byte interrupted artifacts and
bound program inputs. Original intermediate checkpoint bytes, nonempty full-D
logit payloads and complete dataset payloads remain outside this selected
archive. Their recorded identities are retained in the
[original source manifest](original-selected-state/ORIGINAL-SOURCE-MANIFEST.json).

The raw files were published at commit
`ec4f9297abeeeb59b502547663e67a7c46250cf9`. The
[publication result](RAW-EVIDENCE-PUBLICATION-RESULT.json),
[original process output](RAW-EVIDENCE-PUBLICATION-RECEIPT.json),
[successful terminal receipt](RAW-EVIDENCE-PUBLICATION-TERMINAL.json) and
[independent GitHub ref readback](RAW-EVIDENCE-GITHUB-REF-READBACK.json) are
retained with the exact publication script. The thirteen original archive
files are unchanged after their inclusion in this appendix.

A separate standard-library verifier checks the ten part sizes, offsets and
hashes, assembled archive identity, ZIP CRCs, every original member's size and
SHA-256, and byte identity of the embedded and external source manifests.
Its [source](raw-archive-verification/verify_original_selected_archive.py) and
[result](raw-archive-verification/RESULT.json) are retained unchanged. All 2,683
checks pass; all 368 source members and 369 ZIP entries are accounted for, with
no missing or unexpected member. This check uses Python 3.12.14, performs no
checkpoint deserialization, and is separate from the original Torch runtime
model replay. It reports 0.158159 seconds wall time and 0.158166 seconds CPU;
this additional verification cost is not refunded from training costs.

[SUMMARY.json](SUMMARY.json) records the current archive inclusion and
verification status. The earlier failed audit, original unknown controller
outcome, two missing fit terminals and incomplete original costs remain intact.

**Qualification remains HOLD_NO_GO.** Four reconciled stopping outcomes do not
establish all-six terminal completion, whole-trajectory numerical qualification,
complete cost coverage, independent held-out benefit, or ordinary runtime
adoption.
