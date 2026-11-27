# Follow-up to the 22aec Rust consolidation candidate

The source commit is `fead1e01624c9c85ae2207b10c6e267235d2db51`, with tree `2a83406c0deec9e219954182cc4e705b770042e0` and single parent `22aec99e975b2f2e7c3abcfbc32a9ee5bf6a25eb`. Nine source files address the observed URL advisory, Windows junction fixture, literal Git filenames and derived document state, and add an isolated AppContainer current-directory observation.

## Verified changes

- URL 2.5.9 and its required form_urlencoded 1.2.3 update are represented in the original Cargo/Bazel lock pair. The manifest and advisory policy remain unchanged. The original dependency audit and Bazel update/check passed, alongside 66 path URI and nine selected RMCP behavior tests.
- Git filenames containing literal brackets, braces, exclamation marks or percent signs are accepted without expanding them. Declared paths and leases retain their strict grammar. The new real-Git regression, all 29 document self-test controls and seven verification-profile tests passed. The complete main-to-parent path set was replayed successfully with the corrected validator.
- The derived plan audit now reflects the existing DOC-2 work-package state, `source_implemented_execution_pending`. Its authority and external-evidence fields remain unchanged.
- The Windows junction fixture uses a fixed command with two fixed child names. Its assertions for reparse identity, target identity, refusal and absence of side effects remain. Compilation and Linux/collector controls passed; the new nine-case native run is pending. The preceding native run is retained as eight passes and one fixture failure.
- The AppContainer diagnostic changes only the observed current-directory spelling and preserves the existing probe jobs, token, ACL, command and failure behavior. Native evidence remains pending.

## Remaining qualification

Main has not been updated. Remaining ordinary branch histories are still being audited. Windows AuthBus owner admission and elevated sandbox capability refusals remain explicit, and this change does not establish their production qualification. A local replay also preserves the deterministic-merge whitespace failure across historical logs, data and patches; no historical bytes or workflow check were changed to erase it. The remote materialization failure is confirmed, while its raw log could not be retrieved through the connector.

`VALIDATION.json` identifies each source file, evidence archive member and archive part by SHA-256. It distinguishes local checks, prior native failures, unavailable evidence and pending native runs. The earlier `rust-6d7ee` audit directory is unchanged.

The fresh 15:01:21 UTC inventory contains 7,910 refs. Main is the only tip already in its own ancestor set, so no ordinary branch can be retired yet. The newly named HIA branch is excluded, and the unresolved historical identity gap remains recorded.

## Evidence archive

Concatenate `validation.tar.gz.part*` in numeric order. Check the resulting SHA-256 and size against `VALIDATION.json` before extracting. Every member has a separate byte count and digest in the same manifest. Initial environment and sparse-input failures remain alongside the later successful executions.
