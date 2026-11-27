# Library standalone regression fixtures (isolated draft)

These two *original-byte* Python fixtures were recovered from ChatGPT Library and are archived for source custody, not adopted as production fixes.

## Identity
- `hepta_git_replace_local_repro.py`: 2321 bytes, SHA-256 `edf46036fde23390464f87d9e12aa07114988173a0d2fed03b097e63dc3ed98a`, Git blob `4eccd59fa5ddbc1f2fb29c25e6ac68096bf8393f`.
- `hepta_privileged_timeout_regression.py`: 2946 bytes, SHA-256 `010a5764cb729fa3dda1c7564baa34faac4dc2e315012bb2e04f92a58c041057`, Git blob `c09a1f00ef5b5ea14888b48f3aebd8834546d4dd`. Original duplicate `hepta_privileged_timeout_regression(1).py` matches exactly; only one copy is published.

## Independent local reproduction
```sh
python3 library-recovery/standalone-python-regressions-20261103/hepta_git_replace_local_repro.py
python3 library-recovery/standalone-python-regressions-20261103/hepta_privileged_timeout_regression.py
```
The Git fixture demonstrates that Git replace refs can make a vulnerable comparison appear valid and a no-replace comparison reject it. The privileged-action fixture uses a temporary PATH-injected *fake* sudo executable; it demonstrates timeout-byte serialization and non-UTF8 handling, without running privileged operations.

Both fixtures ran successfully in an isolated container on November 3, 2026. These fixtures do not prove current CI or production integration and must not be auto-promoted or merged. Both original Library files passed a targeted sensitive-string check (public Gmail addresses, credential tokens and private keys); the full Library still requires separate security review.

Scope: source and tiny regression fixtures only, no models, original logs, binaries or large evidence. The original dot worktrees, incomplete archives, mixed notebooks, and all other non-source Library material are out of scope and remain retained.
