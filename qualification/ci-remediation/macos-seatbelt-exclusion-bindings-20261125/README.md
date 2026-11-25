# Verify Seatbelt exclusion bindings independent of metadata enumeration

In fac3 macOS Intel job 139157914163, 93 of 95 sandboxing tests passed. The two
failing argument tests expected fixed `.git`, `.agents`, `.codex` index ordering;
the actual policy contained the protected paths in a different order. The full
log SHA-256 is `8964a6d7466046c18d3293b708260ae01702e51142bcf0b8daefbf753fed5f71`.

These tests now compare the complete excluded path set for each affected root.
Every numbered definition must remain unique and contiguous in the generated
arguments, and each must appear in both literal and subpath denial clauses
under that same root. The full writable-root definitions, metadata name regexes,
shell argument equality, actual denied `.codex` and `.git` writes, unchanged
protected bytes, and successful ordinary-file write controls remain.

Only test assertions change. Production policy generation, protected metadata,
permission checks, and sandbox execution are unchanged. A new macOS execution
is required; the candidate is not a passed native result.
