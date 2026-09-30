# ADR 0002: Source observation and evidence retention

Status: candidate qualification design.

Preserve historical `sourceBase` as provenance. After code/docs/workflows are committed, bind `observedAtHead` and source objects to that exact commit in a separate map-only commit. The verifier emits the actual tested SHA/tree/parents. Never place a commit's own SHA inside the tree whose hash defines that commit.

Source freshness is necessary but not a test pass. Exact source-head, deterministic ordered-parent base-merge, current-main, Rust tests, Clippy, formatting and target-host results remain distinct. A failed identity gate must not be reported as successful skipped qualification.

Actions retention is temporary. Retain raw benchmark archives and manifests at content-addressed repository paths with original run/artifact/source identities and hashes. Historical microbenchmarks remain historical microbenchmarks even after permanent retention. Git object identity provides tamper evidence, not administrator-proof immutability; independent object-lock retention is a separate deployment requirement.
