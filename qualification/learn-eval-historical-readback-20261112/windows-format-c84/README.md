# Original Windows formatter failure and exact postimage reconstruction

The original source is `d95c8993b5a80d1636aa74f369586e5b75ef420e`, run 43140461436, job 130925917223. Its only failed step was `Enforce source-level Rust formatting for durable owners`; the native steps before it succeeded and the subsequent directory-acquisition attack qualification was skipped. The job is not a full PASS.

All 31 rustfmt hunks identify seven files whose complete Git blobs and bytes also equal base `c84d35ad0c57d592586cb50fd010547ad7f5c868`. Each old span uniquely matched its source, and all 31 changes were applied in order. No d95-only source, new enum logic or test assertion was copied or changed.

The complete decoded log, original API metadata, exact old/new hunk strings and each source/postimage SHA-256 are retained here. `original-job-log.json` preserves the original text via JSON escaping; encode its parsed `text` as UTF-8 to verify `raw_utf8_sha256` and `raw_utf8_bytes`. Timestamp/ANSI stripping was only used to interpret formatter hunks; the original text is unmodified.

Existing CALLERS rows referencing the changed files have the same relevant marker strings and occurrence counts before/after. All 19 Python QA files were read; the sole direct negative mutation on a changed file retains its exact unique fence/abort needle. CALLERS, its exact digest allowlist and source QA remain unchanged.

The execution environment was unavailable during reconstruction. This is a candidate assembled from original formatter output, not a new formatter or QA execution result. Fresh exact-head CI is still required. No native, full-caller, complete blocking or ordinary-loop acceptance is claimed.
