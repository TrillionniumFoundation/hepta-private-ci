# Original common CI observations

Source tested: d0f3b85fe991d51d23ac6ef0019484aae3a93379.
Common 922f5f9cb258e91d5dafa2a457cf674defd95643 adds only already-closed Bazel lock evidence; source and workflow inputs are identical.

These are complete decoded original GitHub job logs, deterministically compressed with byte/hash readback. No failure is replaced by a later passing attempt.

* Windows core-unit original eight shards passed with the independent original gate reporting retries=0 and flaky=0. The separate core-all target has an original flaky failure in shard 4 and remains OPEN.
* Complete historical owner/formatter comparisons passed.
* Native and default exec each executed 144 cases, zero skipped.
* Original Windows process-wrapper six-case smoke failed before the shard-1 test phase.
* Windows shards 2, 3, and 4 failed. The exact original raw logs preserve all failures and skipped targets.

The complete native-components workflow and the full Bazel platform matrix remain OPEN in this checkpoint. Platform skips, cancellation, retries, FLAKY targets and narrowed follow-up checks are not full-matrix PASS.
