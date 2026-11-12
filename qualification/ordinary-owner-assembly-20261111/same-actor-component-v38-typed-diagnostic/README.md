# V38: preserve actual typed transport errors in bounded diagnostics

Parent: `3dbffb487de65a7c598a92510d081855d8b052dc`, tree `8ad6fd006dbe6b514e5f014e2a12bb50334c08c4`.

The parent V37 attempt passed the original formatter without source drift, then failed compilation during the seven-package scoped fix. Six diagnostic closures incorrectly called `kind()` on `HostIssuerTransportError`, which is an actual Copy/Debug enum, not `std::io::Error`. The [complete failed-parent evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f29be5642ed31600b18eb3cea14167b47df9cd58/qualification/ordinary-owner-assembly-20261111/native-components-3dbffb4-seven/v12) preserves all reached command logs and final exited status. Its fixed source remains unchanged.

This revision changes exactly two Rust files through thirteen unique reversible replacements. The six frontier closures pass their actual enum to the bounded diagnostic recorder. The recorder retains a separate optional transport-error field and leaves the I/O-kind field absent for transport failures. Existing I/O diagnostic callers keep their original values. It does not invent an underlying OS error kind.

The first-refusal rule, nested diagnostic scope merge, debug-only state, 64-output cap, outermost output after the original state guard drops and ignored diagnostic-write failure are retained. All original error mappings, request/response checks, exclusive lane state, permanent uncertain-result closure, original deadline and 500ms freshness rule remain unchanged. No checker, helper, CALLERS, allowlist or test is changed.

Root and an independent reviewer checked every actual pre/post blob and all13 exact operations forward and reverse. These are source reviews, not compiler or runtime PASS. This revision still requires its own original complete seven-package / exact17 actual UID0 Root qualification, with the original checker, retries0 and unchanged budgets. The previously unknown Initial CURRENT FinalUse failure leaf is not claimed fixed.

The isolated future Root CLI, daemon coordinator, B material adapters and lifecycle work are not included in this revision. Ordinary complete / positive adoption / genuine NoUpdate-or-rollback acceptance remains **0 / 0 / 0**. Independent ordinary C and actual daemon-plus-Root OS exit/restart remain unaccepted. Both Drafts stay unmerged.
