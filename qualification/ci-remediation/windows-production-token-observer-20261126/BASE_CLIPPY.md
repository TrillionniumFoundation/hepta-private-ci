# Base Protocol lint correction

The first production-token observation run, source
`bd5a42dac7f14a43b1e36d88a378f31f7c8026ba`, recorded a strict Clippy exit
of 101 before its two original native tests executed. Clippy reported two
redundant clones in `protocol/src/error.rs` and a redundant method closure
in `protocol/src/openai_models.rs`. The original command and diagnostics
remain in the retained run 45769882054 artifact 15094165764.

The correction returns the `String` already produced by
`OffsetTimestamp::format`, and uses the existing by-value
`OffsetTimestamp::to_utc` method directly in `Option::map`. Formatting
patterns, timestamp conversions, error behavior, and protocol types stay
the same. No test assertion or lint rule is removed or relaxed.

The observer and all Windows token, ACL, deletion, and confinement code
remain unchanged. The original native run executed both selected cases
and failed both: the factory case still permitted external deletions;
the legacy case retained three files that should have been deleted in
writable roots. The latter is a different failure from earlier external
deletion observations and remains unresolved.

Validation of this small correction is limited to source review and
format checks until a later exact-source run. Neither a clean Clippy
result nor filesystem confinement is inferred from this edit.
