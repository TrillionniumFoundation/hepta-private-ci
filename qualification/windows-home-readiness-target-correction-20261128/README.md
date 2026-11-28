# Correct the declared readiness test target

The first narrow run preserved here completed the entire original setup binary target (31 passed and its 2 existing ignored workers), then failed before the new library controls because the workflow used an undeclared Bazel target name. The crate macro declares the library target from its BUILD name, windows-sandbox-rs, rather than the Rust package name.

This successor changes only the two library target references and the exact allowed target-name matcher. Every production Rust file, original test, test filter, timeout and failed-attempt rejection is unchanged. The existing three-consumer run remains attached to the original source and is not repeated by this correction. The six new controls and the original missing-readiness control still require actual Windows execution.
