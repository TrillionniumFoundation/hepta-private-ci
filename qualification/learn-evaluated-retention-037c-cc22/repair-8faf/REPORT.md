# Exact 8faf source-gate repair

## Result and scope

The isolated repair contains six changed files over source commit `8faf92e260e118508fc62f4f38f3816db24cd4cc`, tree `d26b9398ffe6ed269c1d018a7e4e043bbe0a2b9d`. The six originally affected source-QA suites plus the evaluated NextUse suite now pass **66 tests / 0 failures / 0 errors**. This was a local Python run over 95 exact materialized files, with identical source inventories before and after the run.

The original full source gate remains a preserved **failure**: 397 tests, 381 observed passes, 11 failures and 5 errors. The repaired candidate has not run a full source gate, full caller verification, native compilation or native tests. All ordinary qualification counters remain zero. This directory does not modify the published progress evidence package or frozen PUBLICATION.

## What changed

| File | Minimal change |
| --- | --- |
| `circuit_next_use_receipt_owner.rs` | In the legacy branch of `predecessors`, bind the original Trainer client to its concrete reference type and invoke its existing `readback` with UFCS. |
| `CALLERS.toml` | Pin that exact replacement body in the existing `fn predecessors(` protected rule. No boundary caller sets, inventory, authority or verifier rules change. |
| `test_original_circuit_observer_source_closure.py` | Follow existing checks into the actual private binding module; protect all 17 owner functions and 9 binding helpers; match profile-aware receipt calls; add only the already registered evaluated C observation caller to the expected tuple. |
| `test_original_published_read_source_closure.py` | Attack the actual RemoteOwner/EvaluatedOwner branches and profile-aware authenticators, keeping the original pre/post owner reads and final checks. |
| `test_original_no_update_stage_source_closure.py` | Add only the already registered evaluated S observation caller to the exact expected tuple. |
| `test_evaluated_next_use_source_closure.py` | Attack the concrete Trainer type, original missing-source refusal and UFCS call. |

The product change preserves the original `ok_or` refusal, original borrowed Trainer, snapshot, exact Training prior receipt, awaited operation and result. The evaluated branch and its independent T/B handling are unchanged. No new capability, identity, signature, factory, execution path or authority is introduced.

The original typed scanner could not resolve the chained receiver `source.trainer().ok_or(...)?.readback(...)`. The concrete receiver and UFCS make the actual call statically attributable without changing the scanner. The old QA failures also reflected helpers that had already moved into `circuit_next_use_receipt_binding.rs`, profile-aware function signatures and two real observation callers. The detailed original-failure-to-fix mapping is in `FAILURE_MAPPING.json`.

## Preserved and extended attacks

The observer suite attacks **102 ordered markers in the owner and 86 in the binding module**. It still attacks the consuming `self` signature in `into_command_owner`; complete pinned predecessor signing bytes and signatures; original source-role and clock constraints; pre/post owner reads; and prohibited key, trust or authority creation.

Ordered mutations start at the complete function item and consume their preceding sequence. This preserves signature checks and directs short receipt argument mutations to the actual call after `receipt_with_domain(`. Standalone mutations still begin inside the function body. Neither signature attacks nor body attacks were removed.

The published-read suite now additionally removes each side of `RemoteOwner | EvaluatedOwner` independently. Original unknown-caller and removal-of-all-registered-callers attacks remain. Every boundary row, privileged inventory row and authority value is unchanged. `INVARIANTS.json` records the manifest comparison and unchanged original verifier hashes.

## Actual execution evidence

| Attempt | Actual result | Meaning |
| --- | --- | --- |
| Original full source on exact 8faf | 397 tests; 11 failures / 5 errors; exit 1 | Preserved original remote failure; no timeout or kill. |
| `local-before` | 44 tests; 11 failures / 5 errors; exit 1 | All 16 failure/error headers exactly match the original full run. |
| `local-after` | 66 tests; 4 failures; exit 1 | Original 16 resolved; mutation helper selected short receipt parameters before the actual guarded call. Preserved as an unsuccessful intermediate attempt. |
| `local-after-v2` | 66 tests; 3 failures; exit 1 | Body-only targeting omitted the original consuming signature marker. Preserved as an unsuccessful intermediate attempt. |
| `local-after-v3` | **66 tests; 0 failures / 0 errors; exit 0** | Full ordered-item targeting and body-only standalone targeting both pass. |
| Parent-run Rust 1.96 rustfmt | Exit 0; unchanged exact product bytes | Formatting of this one isolated product file only. |
| `git apply --check` | Exit 0 | Patch applies to the exact materialized baseline subset. |

The final Python run started at **2026-11-12 10:21:42.337341 UTC**, finished at **10:22:02.462475 UTC**, and reported **19.859 test seconds**. Its log is `evidence/local-after-v3/tests.raw.log`, 15,139 bytes, SHA-256 `e09f0b390002f3fc9ea573a7e9e9170887d42889a4a181451cb4ccd27cbcae6f`.

The product postimage is 24,081 bytes, SHA-256 `aa0ba3925f51d51217cfd37a50ae6b4f2bba88a9d5fdb5b1c91cf3975d11d70e`, Git blob `23e8989ebd2644947b15c80ab9c641a70767de99`. The parent-run format result binds the same bytes before and after.

## Handoff

Apply `changes.patch` to the common source. `MANIFEST.json` binds all six base/postimages, original failure, intermediate attempts, final local run and actual format result. `CALLERS.delta.json` also provides the single exact protected-row replacement for review or a controlled merge. `PATCH_CHECK.json` records patch applicability; `ARTIFACTS.json` indexes the physical deliverable and evidence bytes.

All source under `work/` is an isolated materialized dependency subset. It is not a complete checkout and the local pass is not a replacement for a fresh full source/caller gate on the published repaired commit. The original remote gate and independently running queues were not modified or restarted by this repair.
