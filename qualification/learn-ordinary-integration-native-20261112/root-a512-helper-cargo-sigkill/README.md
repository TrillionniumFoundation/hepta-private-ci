# Actual a512 helper Cargo process termination

The exact 7a8 candidate plus the one-line visibility correction compiled without the former E0624 diagnostic, but the helper manifest records the Cargo subprocess itself returning -9 after 95.86 seconds. The compiler stream has no build-finished event and stderr has no rustc signal diagnostic. The observed failure is SIGKILL of Cargo; these records do not establish OOM, ENOSPC or timeout as its cause. No tests ran and no JUnit was produced.

The complete compiler JSONL, stderr, helper manifest, driver and one-commit source bundle are retained. HEAD/tree and clean source status matched before and after. The limited-debug profile was unchanged, with one Cargo build job. A subsequent debug-zero diagnostic is a separate attempt and cannot substitute for this gate.

After terminal collection, no cargo/rustc/linker was observed in /proc and the old stderr had stopped changing. To prepare space for the separate profile, 156 completed incremental sessions were retired only while holding their original session locks and confirming no working counterpart or recent writes. Both working remnants, dependencies, source and raw records were preserved. Exact paths, sizes, timestamps and free-space observations are included.
