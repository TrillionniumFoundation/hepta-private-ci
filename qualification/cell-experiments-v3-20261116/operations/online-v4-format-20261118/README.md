# Online v4 formatter repair

The full-repository Python formatter rejected 26 existing online v4 modules in
job 134744511193 at merge b97e88e39a233d09ee4927e046779d00c8f3e65a.
The CPU profile base already formatted the shared-pool fixture. This change
applies the pinned Ruff formatter to the remaining 25 modules.

`AST_EQUIVALENCE.json` binds the original and formatted bytes of all 27 modules
and records identical parsed ASTs with source locations excluded. The original
CI gate and its discovery scope are unchanged. `just fmt`, the scoped Ruff
format check, and the source whitespace check pass. No behavior change or new
model measurement is claimed. The repository's mechanical-change size exception
applies to this formatter-only source diff.

The current training and Circuit runs retain their separately frozen original
source directories. This checkout is a later source version; it does not replace
or relabel those execution receipts. Full engineering tests passed on the
semantic base before formatting; no tests were rerun after the formatter.
