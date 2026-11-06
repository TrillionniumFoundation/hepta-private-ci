# Restrict manual helpers to the current target configuration

This correction completes Unit20 before product publication. Unit20's original
candidate, tests and four evidence files remain frozen. Its provider filter
alone could select a compatible exec-configured instance of a label whose
current target-configured instance was incompatible.

The new selector wraps only the native Windows configured query in
`config(original_query, target)`. Its Rust rule kind, manual tag predicate,
workspace scope and V8 exclusion remain exact. Compatibility is then tested on
that target instance. Other platform branches keep their original query.

## Actual counterexample

One real Bazel 9 server ran all eight commands without `clean` or batch mode.
The target and host both used the declared Windows MSVC platform. The fixture's
exec transition selects `opt`; its top-level target configuration is `fastbuild`.
One helper accepts only `opt`, creating a controlled compatibility difference.

Before the exec transition, Unit20 selected two correct helper labels. After
priming the exec dependency, the same query returned both configuration hashes:
it incorrectly included the optimized-only helper and duplicated the unit helper.
Adding `config(..., target)` returned only the current target hash and restored
the two correct labels. No compile or test actions ran. This models the general
configuration ambiguity; it does not reclassify the original 169 CI failures.

The shell regression checks the exact query sent through the actual query
wrapper. Frozen Unit20 fails that new assertion in both LF and CRLF cases;
the effective candidate passes all 52 wrapper methods with no skips. Query
failure propagation, empty-set refusal, cache options and scope checks remain.

`configuration-counterexample.tar.gz` contains an indexed, lossless record of
the fixture, every command and output, both source versions and local tests.
The platforms archive needed for replay is retained in Unit20's evidence.
Hashes and result boundaries are in `VALIDATION.json`. Full native Windows
Clippy on the integrated product head remains pending.
