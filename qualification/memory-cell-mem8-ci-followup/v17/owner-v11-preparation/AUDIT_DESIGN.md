# Owner V11 local generator review

This preparation creates no Git object, branch, workflow run, host command or model request. `prepare_owner_v11.py` only reads frozen local JSON and writes a new local proposal directory after all checks pass. No final owner ledger has been rendered during preparation.

## Baseline and allowed changes

The baseline is the actual published V10 `BLOCKERS_FINAL.json`: 134,567 bytes, SHA-256 `bac85ca6969f7fe47b75245cb688bbcf995871204e5ad921c327df736aa85b36`, Git blob `2d5f0256776089b386f8e5ebd9d9eefcbfaac5f2`. Its owner head is `f86dfb058edd6e489671e99baf7643a58e7eed35`; a separate actual-publication receipt must confirm that identity when rendering.

The generator replaces only checkpoint metadata, the owner publication proposal description, HOSTED-CI's status/finding, and that gate's current missing-input/next-step descriptions. It adds `source_ci_followup_v9_v11` and `v11_update_provenance`. Earlier source fields are retained as historical records; the additive section explicitly identifies which current-source label supersedes them.

The original `closed_this_followup` array remains wholly byte-for-byte unchanged with all 18 entries. New completed software/source work is listed separately within the additive section. The nine non-CI gate objects, their nine intake objects, the HOSTED-CI closure and intake closure-evidence strings, all other intake fields, and every other prior top-level value retain their original UTF-8 value spans. The final audit checks both parsed equality and those exact bytes.

All ten adoption gates remain open. `NoUpdate`, `HOLD`, production-adoption false, original provider admitted-turn/unknown physical-request count, H unknowns, original scientific findings, zero new scored actor episodes and zero new real model requests remain unchanged. Neither a source gate, package test, audit-mode Fence result nor archive custody closes these gates.

## Actual results, without cross-source transfer

`freeze_report_selections.py` reads explicitly named original audits and freezes their full size/SHA/Git identity, exact JSON-pointer selections and expected fields. It does not execute their archived commands. The current frozen selection uses the original 17:58:08 UTC blocking snapshot, which is explicitly nonterminal. It is not a final-run substitute. For the final checkpoint, name the actual later snapshot explicitly and freeze a new selections file; retain this earlier file.

The selection covers V9/V10/V11 source-only gates, exact-d0f MEM/Architecture/Private/two-native, the isolated Fence audit and the different ordinary d0f blob-policy job, actual Windows/Mac failures, earlier c895 five-case partial qualification and original d0f dirty-lint failure. It preserves case repetitions, synthetic reader scope, cached targets, flakes, missing terminals and unknown causes. Each selected field is extracted from its hash-pinned report at render time. Evidence mapping must match the full report/member bytes. No package result is transferred to the dynamic current source merely because its tree or ancestry is related.

## Publication parameters

No final source or evidence head is predicted. Rendering requires a hash-pinned bindings JSON with three separate actual publication records: current source PR5935, evidence PR5889 and previous owner PR5897. Each record names a local receipt and exact selectors for its head, tree, PR, draft state, raw ref head, successful update and full-body equality. The source base remains the frozen common `96038ccf0660154fac143ba6cbe4be81e00813e8`.

The bindings also map each frozen report ID to its actual published evidence path and full identity. A report inside an archive names that archive path plus the exact member; the identity then refers to the extracted member bytes. `root_full_readback_verified` is a supplied root audit assertion, not a new remote read performed by this generator. Missing final bindings fail before any output directory is created.

The generated owner record says `PREPARED_UNPUBLISHED_OWNER_CHECKPOINT_REQUIRES_EXPECTED_HEAD_CAS`. It never claims the owner proposal is already published. The subsequent real owner publication must be recorded separately after the root's successful expected-head update and full readback; the ledger cannot contain its own future commit hash.

## Local verification and limits

The preparation checks Python syntax, strict baseline identity and all report-pointer/expected-value selections. Offline invariant controls use only the actual baseline in memory: an allowed descriptive edit preserves protected spans; intentional changes to a non-CI gate, prior closed entry, HOSTED-CI closure, provider count or scientific acceptance are rejected. These controls are generator validation, not native, actor, CI or scientific tests.

The generator rejects duplicate JSON keys, mismatched frozen files, unexpected output keys, gate-count changes, unbound publication selectors and overwrite of an existing output directory. It does not itself authenticate the remote server; actual receipt and binary/member readbacks remain the root's separately recorded evidence. It does not infer current required-CI acceptance from selected passes and keeps that acceptance false.

The final reviewed facts file and actual bindings file are explicit SHA-256 command-line inputs. Original receipts and snapshots are never rewritten. Any later facts update needs its own frozen input identity and review; there is no implicit latest-file lookup.
