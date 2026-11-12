# Late-writer source-closure guard correction

Status: fixed-source static candidate; original Python verifier and new QA tests have not been executed for this candidate.

## Exact scope and observed failure

Base: `0081b6b78fa1f0fb238a12aec814c93bdf2343a0`, tree `87e7ef749329b0f41481873a414cdd924d5971bf`.

The original B4 log `15f19a1c30f69cfb595732292bbc17754daf1dd1` (67,215 bytes; SHA256 `3154d7e5e0ccf8d4f06b5cb9bdc918d8f92020adc650b96b86f1649b428abbe3`) records 211 tests and 12 errors. Eleven are RootAdmin setup errors from the same `select_original_startup_entry` protected-order check. The separate `source.readback()` closure error belongs to another patch.

The original checker `7a6709691c372504ca11b5d2a74e14ba819fca8f` masks Rust string literals before matching ordinary code-order markers. The original combined condition therefore cannot match. Its two `return Err(` markers are valid ordered matches and are retained.

## Correction

No production Rust is changed. CALLERS changes only four lines in two existing protected rows:

- Register exact `Some("late-writer")` through the original `literal_calls` mechanism. Keep the real comparison prefix including `!=`, duplicate rejection, wrong-value rejection and selection order.
- Register exact `required_path("CODEX_HOME")` through the same mechanism. Preserve `?,` before the existing `std::env::current_dir()?` guard.
- Retain the four complete original labeled canonical/path calls as raw `required` strings.
- Protect the actual canonical/path operands and expected operands in masked code, then `)?;`, then the next real guard. A following call's propagation suffix cannot substitute for a removed earlier suffix without moving the next required guard behind the cursor.

The path labels only enter existing error formatting. Raw requirements preserve their original spelling somewhere in the source; they do **not** prove the diagnostic label's actual literal span. This candidate does not claim to reject an altered same-length diagnostic label accompanied by the original text in a comment. The two selection/environment literals above retain actual-code literal-span checks.

All 504 boundary blocks, inventory/caller sets, ignored paths and other protected rows remain byte-identical. The protected row count remains 366. The original checker and all existing QA tests are unchanged.

## Mutation coverage

The new `qa/b4-no-bypass/test_original_late_writer_entry_source_closure.py` has 10 methods and 22 mutation cases. Each first verifies the two real source rows using the original `_verify_protected_files`, then expects a specific original failure class. It restores the source after each mutation.

Coverage includes changed or comment-forged entry values; reversed `!=`; removed duplicate rejection; changed or comment-forged CODEX_HOME; removed CODEX_HOME error propagation; four removed/comment-replaced path guards; four changed actual paths; three changed expected paths; and four removed path error propagations. Path mutations keep the original raw call in a comment so raw-text matching alone cannot satisfy the test.

These are source-closure tests. They construct no owner, grant, receipt, handoff or business input.

## Verification and limits

V8 checks established exact forward/reverse replay of four replacements, byte-identical boundary blocks, expected postimage Git/SHA256 hashes, and exactly one original source occurrence for every proposed mutation. A static scan of the CLI-related six paths, eight protected rows and 13 function-order entries found no remaining quoted sequence marker outside its declared literal_calls.

The local Python process could not start because the executor was unavailable. No Python verifier/test run, AST check, Rust/native command, remote h request, shared-source mutation or ref change was performed for this candidate. Root owns the subsequent original QA and full source gates. Independent review is separate evidence, not execution.

Root parent count remains 17. Ordinary complete, positive adoption and ordinary NoUpdateRollback remain 0/0/0. No prior passing test is inherited by a new integrated source.

## Frozen deliverables

- CALLERS postimage: `e6dcf7d4a71061772c720c9ba355ed646d1cc88e`; 669111 bytes; SHA256 `1b222ab62ddf5f3a808a18a922f5f0b9d804c49ff606956bfd8e2b1d1a9233e9`.
- New QA postimage: `a09ec96ea064b35216e43b17dd4726d3a36afc7e`; 6674 bytes; SHA256 `4b7a1453784b1304bba8062e4854e8fcf4de9b99cd35c55eb2d701517462f7ef`.
- Reversible operations: `4945829d980f453381ae876e288880f78acb54e1`.
