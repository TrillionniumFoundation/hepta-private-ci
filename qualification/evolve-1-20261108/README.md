# EVOLVE-1 implementation and observed result

Code commit: `b83de1a192a4c35c12563d8856ffded238469a21`. Dependency: PR #5345, `1e9c2890fef92ea63dab472e1bdb0c444c9656b5`.

## Result

**Engineering execution is verified; scientific and native adoption qualification remain HOLD.**

The frozen run completed 3 independently seeded improver-discovery processes, 12 four-arm runs and 72 admitted candidate attempts. The earlier 72-attempt development run is retained separately. Each discovery process evaluated eight replay-policy configurations; its history cost is separate from the subsequent four arms.

| Cell | Runs | Mean heldout gain (percentage points) | Mean retention loss (percentage points) | Observed numerical criterion | Complete qualification |
| --- | ---: | ---: | ---: | ---: | --- |
| S0-I0 | 3 | 14.7135 | 9.6354 | 3/3 | 0 qualified; 3 unresolved |
| S0-I1 | 3 | 8.8542 | 2.6042 | 3/3 | 0 qualified; 3 unresolved |
| S1-I0 | 3 | 14.0625 | 10.1562 | 3/3 | 0 qualified; 3 unresolved |
| S1-I1 | 3 | 8.8542 | 3.7760 | 3/3 | 0 qualified; 3 unresolved |

These values are descriptive observations on generated tasks. All four cells meet the pilot numerical threshold in their three observed runs, but the descendant improver produces less adaptation gain and less retention loss. It does not demonstrate superior improvement efficiency. Three discovery seeds do not justify a confirmatory population claim.

Measured driver work: 11.765027 wall seconds and 1.539569 CPU seconds. The whole-second inherited selection timestamp contract contributes waiting time. Driver/import/publication overhead and physical energy/provider metering are not fully qualified; unknown costs remain null. Complete improvement cost is not reported as zero.

## Delivered behavior

- Four-arm component transfer with identical within-row solver state, task and budget context.
- Separate observed effect, retention violation and complete-cost qualification fields.
- Complete attempt registration, failure/UNKNOWN preservation and NoUpdate exclusion.
- Cross-split source and data-digest checks, frozen improver identities, and history-cost separation.
- Bounded reference learning, cooperative dispatch budget checks, atomic recoverable checkpoints, retained original evaluation and selected model bytes.
- Explicit false authority/scientific/production flags; no native selection or successor receipt is fabricated.

## Verification

- 41/41 tests passed, including the inherited causal comparison suite and 16 new transfer/pilot tests.
- Ruff 0.15.13 format, format check, and selected fatal lint checks passed on the original rog runtime. All five modified Python files retained identical ASTs through formatting.
- The full exact-base repository `just fmt` was not executed in this exported subset. No Rust source or dependency was changed.
- Candidate GitHub CI is reported separately from these local/native receipts. This evidence freeze does not claim it passed.

## Remaining qualification work

1. real task/source-group registry and fresh confirmation panel.
2. HeptaCore/trainer integration and independent native evaluator.
3. complete calibrated cost profile including historical R&D and external runtime overhead.
4. native selection/NoUpdate and actual next-task consumption/recovery.
5. confirmatory sample size and independent improver lineages; candidate CI/integration.

## Files

- [Protocol and primary research sources](PROTOCOL.md)
- [Current machine-readable status](CURRENT.json)
- [Final raw campaign](campaign-final.json)
- [Development campaign kept separately](campaign-development-01.json)
- [Execution index](execution-index.json)
- [Retained journals, improvers and selected weights](retained-artifacts.json)
- [Test result](unit-tests.json) and [full log](unit-tests.txt)
- [Original format receipt](format-receipt.json) and [verified readback](format-readback-receipt.json)

The synthetic pilot uses a NumPy reference learner. S1 is an explicit fixed preparation update. The evaluator verifies local retained bytes only. These are deliberate execution-scope declarations, not evidence of HeptaCore benefit, independent owner isolation, real task-family transfer, or general RSI.
