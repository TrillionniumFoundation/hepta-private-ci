# C3 applicability parsing cache component

This is a two-file patch against exact C2 `03521b2f32346a49cccde8ff72e8c7b886b31222`. C2 is unchanged. The patch reduces repeated parsing in `report_module_evidence.py`; the complete C3 original 300-second applicability gate remains pending with the integration owner.

Each of the two pure transforms has its own 128-entry LRU keyed by the complete current `str`. Every existing `safe(...)` and `read_text()` call still happens before the transform. Texts longer than 262,144 characters receive the original full parse without being retained. Rust returns its original immutable mask string. Python returns a `frozenset` so a caller cannot modify a cached symbol summary. No path, modification time, selector verdict, registry relationship or successful validation result is cached.

AST comparisons confirm that all other checker functions, the Rust parser body, the Python symbol traversal, and all existing applicability test classes retain their original logic. The two-file patch was applied to independent exact-base copies and reproduced the candidate bytes exactly. No workflow, timeout, memory allocation setting, registry or coverage declaration is changed by this component.

## Recorded local validation

The five new `ParserCacheMutationTests` passed. They cover warmed Rust and Python parsers after same-path, same-size, same-mtime content replacement; accepting the new content and a restored original; comments/raw strings/unattributed helpers; missing and escaped paths; and preventing caller mutation from polluting future Python symbol results.

The eleven original `RustImplementationOwnerTests` and the original `SourceApplicabilityTests.test_class_and_method_source_bindings_are_distinct` also passed, using an unchanged exact C2 `test_responsibility_evidence.py`. That file is local validation support and is not part of the patch.

Commands and raw stdout/stderr are retained in `local-selected/receipt.json`. Hashes before and after the selected commands are identical. This is an isolated patch sandbox, so the original Git-root project preflight returned 128 (`not a git repository`); that result is retained. It is not a complete source qualification. The integration owner must run the original preflight in the full C3 checkout before applying/building/committing the candidate, then run the complete original suite within its unchanged 300-second budget.

`manifest.json` provides exact base/candidate Git blobs and SHA256 values, patch hash, selected receipts, preserved invariants, and the remaining full-checkout gate. The local controls and independent static review do not establish that the original timeout is resolved.
