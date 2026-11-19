# Windows cached-replay fixture correction

Source-head run 42743683229 at 8a1d947 passed Linux and macOS but failed two
inherited cached-replay tests on Windows: launch configuration bytes changed.
Both new native collection tests passed on that Windows run.

The test helper used Path.write_text(canonical(value)), which translates LF
to CRLF on Windows while the fixture config hash commits to canonical UTF-8
bytes. Write those exact bytes with write_bytes(...encode("utf-8")) instead.
No production replay check, configuration, source freeze or training input changes.
Final formatting is AST-identical to the tested correction.

Local 101-test validation is adjacent. Hosted validation belongs to its own
commit/run; the original failure is retained at
https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42743683229
