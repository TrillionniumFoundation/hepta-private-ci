# Fix original five-arm E3 Actions expression escaping (2026-10-15)

**DRAFT / DENY_ALL.** Both the source contract and physical OCR/native workflows inherited literal backslashes before GitHub expressions such as \$\{{ github.sha }}. The original exact-head job [38684683661](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38684683661) failed in its checkout step with `fatal: invalid refspec '+refs/heads/\\82f711a...*'` before any tests. This is a checkout expression parsing failure, **not** a scientific result or model quality failure.

This additive fix removes only the literal escaping character from GitHub expression references in the two existing five-arm workflows, including checkout SHA, concurrency groups, scoped runner-temp artifacts and GitHub token. It adds this research child branch to their push triggers to obtain a real exact-head CPU/physical evaluation without needing a production/main merge. All original model+dataset source pins, independent held-label scoring, `blocking-ci`, security, original access permissions and DENY_ALL constraints remain unchanged.

No success is asserted until the corrected exact-head model/CI jobs actually finish. Missing original OCR/native model weight/label/source material fails closed. No automated Stem winner or FinalUse.
