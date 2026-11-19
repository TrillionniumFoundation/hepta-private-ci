# Round 08 — bounded replay reuse and original deadline regression

This increment builds on `7f66ba922ad96d3b2153c2b12f5e28bc56ce3e1a` in PR #6293. It changes five Rust files in the product execution journal and preserves their exact tested native postimages.

## Behavior

The journal may reuse only pure replay parsing of a previously verified image at most 256 KiB. A hit requires identical bytes, binding, and retained minimum anchor. Each operation still reads the original held file, compares complete physical images and retained length/digest/records/anchor, restores the exact cursor where required, and preserves sticky failure poisoning. A write attempt clears the memo before any write. The memo does not retain authority or substitute for original witness checks.

## Verification

- The complete `codex-hepta-intelligence-eval` package passed 226 tests with zero skipped.
- The original `original_next_use_evidence_timing_diagnostic` passed without changing its 500 ms deadline. Command readback was 248.483 ms and evidence readback was 245.866 ms. All original peer terminals returned success. The other 1,699 tests were outside this explicit diagnostic filter.
- Scoped `just fix` and `just fmt` passed with no source changes. The final format pass including the Python fixture also passed with all six source files unchanged. Tests were not repeated after these commands.
- The complete original caller verifier passed: 1,645 boundaries, 820 protected files, and 7,873 Rust source files; `authorityGranted` remains false. All caller allowlists are unchanged. The extracted replay definition markers and two protected records are bound to the real implementation; the new memo has its own protected record. The other 817 protected records are unchanged.
- Three existing Python semantic tests passed after spelling the same deliberately invalid fixture bytes as `"u" + "e" * 127`. This fixes the Codespell result without changing the payload or adding an exclusion.

The first diagnostic build lacked two compile-time directories in the isolated sparse checkout. Its failed log is retained in the verification report; restoring those exact base-commit inputs allowed the unchanged diagnostic to run. The initial caller scan also retained an obsolete marker for the extracted replay loop. That failure is recorded in the local audit, and the replacement markers preserve physical observation, full image/state checks, exact cursor restoration, and sticky poisoning.

`verification.json` binds source and native log hashes. `caller-proof.json.gz` contains the complete successful original caller receipt. `caller-manifest-changes.json` contains the exact revised source constraints.

## Remaining integration work

The separate large Rust merge and its native package qualification remain in progress. Chrono removal, remaining platform failures, and the repository's required checks must be resolved before updating main. No branch is deleted in this increment. The protected HIA inventory from round 07 remains outside all ref updates and source integration.
