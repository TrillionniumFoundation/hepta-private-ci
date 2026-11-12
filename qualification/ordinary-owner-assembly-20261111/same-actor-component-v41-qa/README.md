# V41: actual-source QA and caller metadata correction

Parent: `53ed651d9bbaac6b6c0500d390b730f5910a2fa2`, tree `8b3769abd84c13ed24ef7d2d7ceeb7bd77e5481c`.

The actual V40 entrance failed in `qa/b4-no-bypass`: 221 tests, 13 failures and 25 errors (executor 183 passed / 38 failed). That record remains failed. Native formatter, seven-package fix and binary check had passed without source drift; later qualification stages were not reached.

This candidate changes seven QA files through 18 exact operations, five existing CALLERS rows, and only the digest of the existing CALLERS blob-size exception. Four protected rows gain the six explicit arrays required by the unchanged original schema. `final_use_open_state` gains its real existing sixth caller in both independent inventories. QA fixtures remove the same original guards at their actual current source positions; finite caller sets include the existing concrete phase sources. A Session fence fixture hidden by the original schema failure is corrected as a separate static finding, preserving phase closure and worker abort while deleting only the original fence.

All 48 existing methods, setup/rejection helpers, assertion method sequences and omission/unregistered-caller mutations in the six Python files remain. Root verified exact forward and reverse edits, all 38 original failure titles, fixed-source pins, finite caller tuples and scoped guard-deletion projections. Independent reviews cover both the QA packet and Root-authored metadata. These are static checks, not original checker or native execution results.

No Rust, checker, typed helper or native harness bytes change. No future B/CLI/Session/Circuit/daemon/retirement draft is installed here. The immutable original full qualification entrance must run again against the new commit, without inherited passes, bypasses or narrowed selection. The 500 ms original-request freshness rule remains unchanged.

Ordinary complete / positive adoption / genuine NoUpdate-or-rollback counts remain **0 / 0 / 0**. Independent C and actual daemon+Root OS stop/restart are unaccepted. Draft-only staging; no main merge.
