# Recovery of the interrupted publication — 2026-10-30 UTC

The user authorized public release of all project code, checkpoints, raw data and evidence. The temporary executor workspace was reset after the scientific work completed and while Git blob uploads were in progress. At recovery, the branch still pointed to `8a3472815af33dc634ce3e798546704d5e48d3c7`. All 60 training candidates, 300 checkpoints and sealed validation selections were already reachable there.

This commit anchors the original report002 HTML, its original receipt, its figures and corrected presentation sources using their already uploaded Git objects. The recovered HTML has SHA256 `1c712e7fa11dd67c95b0fb5a373962d057a92b96fe6cb8f08a948c7358c67fa5`. Its original report receipt has SHA256 `e531f9be028d52a20e9c92e987557c70b8bb4c7ed2cabd3426bb7462a2436c8a`.

Publication recovery is not complete at this commit. The original report receipt refers to files that are not yet all reachable from the branch. In particular the report002 summary upload was not confirmed. Recovery will distinguish exact original bytes, deterministic reconstruction verified against an original digest, and newly repeated verification. No models will be retrained or reselected to improve the scientific result.

The completed report records zero of 24 registered metric-improvement gates passed, 24 of 24 trained end-to-end numerical checks passed and 7 of 8 independent continuous-flow checks passed. Scientific failures remain part of the evidence.

The complete archive created before reset had 1,213 evidence files, 15,926,965 bytes and SHA256 `a8ce9dccf74ff31521e736d52a238d57b689e3431f35157b451e82b4883327d8`; these are historical identities, not a claim that the archive has been recovered. Its final audit identity was `e9cca63657c97dfbc597a8e21d20f23a203d84745c2a19bef19ac809086f98f5`. A later recovery archive must use its own identity unless its bytes match exactly.

This interruption is separate from the earlier unavailable historical commit `b1806a2e2c811e7ef5b15848ba262664aa34363f`, whose original raw weights and complete archives had already been reported missing.
