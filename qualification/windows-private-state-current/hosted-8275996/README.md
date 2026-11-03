# Original failed qualification and narrow successor

Workflow 41713496978 tested source 8275996f2c589a96843e116ac6f2c1d194ef3d2b.
Its original failures remain failures.

| Original job | Observed result |
| --- | --- |
| Windows 126187377199 | The two selected acquisition positive cases executed and passed. The reader then rejected nextest's new progress column. Neither production mutant nor the four complete libraries ran. |
| macOS 126187377339 | Path utilities 4, contracts 174 and prompt registry 50 passed. Agentd executed all 173 cases: 166 passed, 7 failed, zero skipped. |
| Linux 126187377638 | All four complete libraries passed: 7, 174, 50 and 173 cases, zero skipped. Original scoped Clippy succeeded. |
| Bazel 126187376854 | Original committed-lock check, update, repeated check and four complete library targets succeeded. The actual generated lock equals the original committed bytes. |

The Windows native output contains `(1/2)` and `(2/2)` between elapsed time and
the package name. The old reader accepted neither line. The new reader parses
this optional progress column and checks its exact two-case inventory. Exact
test names, outcomes, summary, filesystem observations and command exit codes
remain mandatory. Eight reader controls cover old and new output, ANSI/CRLF,
repeated final status, inconsistent progress, missing cases and wrong failures.
The selected acquisition filter intentionally excludes unrelated cases; it is
followed by complete libraries in a successful qualification.

The seven macOS failures occur before their intended assertions: three HNMF
fixtures use a noncanonical temporary root, one external replay checkpoint uses
the same alias, and three socket cases exceed Darwin's native socket path limit.
The successor canonicalizes only fixture-owned paths and creates the two Unix
socket fixtures below a short random temporary parent. Windows keeps its original
temporary location. All original assertions and production path checks remain.

The exact original Windows positive log and failed Agentd JUnit are retained as
lossless gzip. Their original ZIP sizes and digests are recorded separately.
The complete original ZIPs have been downloaded and hash-checked for a separate
evidence checkpoint. They do not confer qualification on the successor source.

Run `python3 PATH/replay_progress.py` from a clone containing the original commit
to reproduce the old reader rejection and the current reader acceptance of the
same actual native output. This replays log parsing only. The new native, mutant,
Clippy and Bazel qualification must run again on the successor head. No timeout,
identity, failure handling, assertion or admission policy is weakened.

DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO remains in effect.
