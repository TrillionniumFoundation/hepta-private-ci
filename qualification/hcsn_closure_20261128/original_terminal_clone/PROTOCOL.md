# Original production host clone repair

Static review of exact head `4163ab5e400a38b34de502de5bee5d44f62d9679` found that the existing derived `Clone` host contained a new bare `AtomicBool`. No compiler failure is claimed: the attempted native setup had already stopped at an independently stale source-list pin, before Cargo started.

The actual operation attachment clones the recovered host. The claim is now an `Arc<AtomicBool>` in both existing constructors, so every clone retains the same irreversible claim. No store is reopened and no writer, trust or authority is created by this fix.

Before any of the four factory controls execute, the existing first control is strengthened: clone the real host before its first claim; drop the original terminal bootstrap; retain the original repeat-refusal assertion; load the same Fleet identity into another Config and attach that earlier clone; require the same already-assembled refusal. The original four function names remain fixed. This adds no fit, scientific sample or separate experimental cohort.

Only the new host-field guard spelling changes to match the shared type and constructors. All older guards and the prohibition on resetting the claim remain unchanged. Actual `just fmt` finished with exit 0; the compressed original receipt and formatted postimages are retained under the digest in the adjacent record.

The native 26-function gate remains pending on the repaired combined head. Original setup-refusal evidence, scientific ceilings and the shared 3,600-second engineering pool are preserved.
