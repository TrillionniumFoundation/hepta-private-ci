# age i18n maintenance backport

This directory contains the published `age 0.11.5` source and its complete license
files. `HEPTA_SOURCE.json` records the archive checksum and every original file hash.

The functional patch changes only the normalized Cargo manifest: `i18n-embed` advances from 0.15 to
0.16 and `i18n-embed-fl` advances from 0.9 to 0.10, matching the official
`age 0.12.0` maintenance change. The resulting macro implementation uses maintained
`proc-macro-error3`. Before repository formatting, all age runtime source is byte-identical to
`age 0.11.5`. Encryption formats, recipient types, parsing checks, and supported
features retain their original implementations.
The original upstream manifest inherits workspace dependencies and is preserved.

A complete upgrade to `age 0.12.1` currently adds `crypto-bigint 0.5.5` through its
new HPKE/P-256 support. That version predates the fixes for RUSTSEC-2026-0387.
This backport avoids introducing that vulnerable stack; it does not disable an
existing feature or exempt a dependency from advisory checks.

Remove this local patch when a published age release supplies both the maintained
i18n dependency and a fixed cryptographic dependency graph.

## Repository formatting provenance

`HEPTA-maintenance.patch` records the functional changes before formatting.
It applies to the recorded official source (or, for the existing Starlark
backport, the recorded repository base).
`HEPTA-formatting.patch` records the subsequent mechanical changes from
`just fmt`; it does not belong to the functional maintenance patch.
The source metadata records both pre-format and final hashes. Targeted tests
were run before the required final fix/format step, in the order specified by
the repository instructions.
