# Independent review of the original worker library gate

Reviewed the frozen workflow blob `af1f7ca8fafd98a495bfa2c54e3de4130d856aca` (SHA256 `652edd3c54408eb9613653538f1e58c6ba6f73a5c123ae6fe7bd0e75c895f702`). No blocking source defect was found in the reviewed trigger, original command selection, source identity, JUnit validation, or final qualification logic. This was a read-only review, not an execution of the workflow or its worker suite.

## Checked boundaries

- Pull requests trigger on relevant source and build changes without a branch or Draft exclusion. Checkout uses the immutable PR head, removes retained credentials, and compares every tracked blob, file kind and executable mode to that head. Before and after every command, source and locks must remain unchanged.
- The original prepare action, compiler 1.95.0, nextest 0.9.103 and original native setup remain explicit. The V8 step clears both overrides and uses the original resolver; it does not accept arbitrary pre-set archive paths as verification.
- The command is the complete original `codex-hepta-infer-worker-host --lib` suite, with the original profile and retry policy. There is no test-name filter. Its eight required regression names must appear in the correct single-library JUnit suite and pass; missing, skipped, duplicated, mismatched-package, counter-inconsistent and final failed/error cases refuse qualification.
- Independently rehashed the pinned nextest reporter, `RustBinaryId::from_parts`, and original XML fixture. The original library ID uses the Cargo package name, including hyphens. The original zero-only omitted skip counter / suite `disabled=0` representation is supported without accepting a missing nonzero skip count.
- A fresh JUnit report is required. The final result requires every setup/format/test/fix/final-format step and every command to succeed, plus exact final source identity. An earlier error or source rewrite cannot become a qualified result merely because the artifact upload succeeds.

## Scope still open

The actual eight worker cases and full worker library have not been executed by this review. The author’s synthetic checker suite is evidence for the parser, not product behavior. The original retry policy remains enabled and is reported. This workflow does not establish crash-durable RunCancel, a production signing/checkpoint service, full-workspace/Bazel qualification, or native guest/device qualification. Publication must verify the new workflow path against the actual stack head and combine it with the separately frozen worker source candidate.
