# Make the transcript guard scope explicit

Base: `eb294db1b084746d3f24ae4a07c7a0d3b1bf8e19`.

The original GNU Clippy job `140218309346` reported
`clippy::await-holding-invalid-type` for the named Tokio transcript mutex guard
in `cumulative_transcript_survives_delta_lag_and_polling_drains`. The repository
explicitly lists Tokio lock guards in its disallowed-across-await types.
This occurred after the private import repair; GNU release compilation passed
in its separate original job. Neither result establishes all test cases passed.

The original source already called `drop(transcript)` before awaiting the output
buffer lock. `output_handles()` returns a borrowed `&OutputHandles`, so this is
not evidence that a temporary owned output handle was kept alive, nor proof of
an actual deadlock. The smallest source change makes the existing lifetime
boundary lexical: the same transcript lock and entire four-field assertion are
inside a block that ends immediately before the later output-buffer assertion.

The four asserted quantities, expected vector, byte limits, producer inputs,
slow-receiver checks, both original test functions and their names, all await
operations, and the one-second producer deadline remain unchanged. No lint
allowance, dependency, production code, environment setting, retry or assertion
is changed. No replacement test is added for this syntactic scope adjustment.

Source identity, whole-file inverse, protected source/lock files, `just fmt`,
diff whitespace and spelling are checked locally. Native Rust compilation,
Clippy acceptance and actual test results still require normal CI. No existing
run is cancelled or rerun to obtain a result for this candidate.
