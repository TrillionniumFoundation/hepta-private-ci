# Current research CI repairs

This review is pinned to c0e525fd94e6eea2957bd1a12764627b86dd71ec.
It repairs two existing baseline inconsistencies in four paths.

The joint runner keeps the original 2026-11-12 manifest and evidence unchanged.
A separate current manifest pins the same 20 paths with the two already reviewed
HPCA updates. All 15 earlier HPCA tests and 41 earlier admission checks remain.
The current invocation passed 88 test executions and both original probes.

The confirmatory tests now read the original 384-row historical metadata and
verify its existing immutable hash. They do not invent historical image IDs.
All ten original tests and 23 assertion expressions remain. The full scoped
command produced 171 passing test lines, plus the original class-level skip for
missing real model inputs. A class setup skip is not part of the 171 executions;
the earlier chat shorthand of 170 passing cases plus one skip was inaccurate.

The source size policy, Codespell, Prettier and the runner's locked Ruff check
passed. The unchanged original formatter selector selects no groups for these
four paths; this is not a claim that a partial checkout ran the full format gate.
Every other entry in the current tree retains its exact mode, type and object ID.

The evidence archive preserves original hosted failures, local failures,
complete successful output streams, source pins, semantic checks and three
rejected mutations. Its manifest lists every regular member and original
SHA256. Verify the compressed hash, decompress the gzip stream, inspect the
relative member names, then extract into a new isolated directory and verify
each member hash. No member is a link or an absolute path. No old receipt is
rewritten, and these checks grant no model or production qualification.
