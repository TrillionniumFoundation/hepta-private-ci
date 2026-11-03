# Fleet immutable publication on the actual platforms

The original macOS ARM run at `c7629f5366434bc146ef961b873d2babe79e93aa`
failed one workspace canonical-path fixture and four release tests with EACCES.
The current Fleet source and those fixtures are byte-identical to that source.
This first revision changes qualification only and does not claim a repair.

The workflow uses ordinary unprivileged Linux and macOS runners. It compiles the
exact current production copy, chmod and directory-sync functions into a small
standard-library-only operation probe, with both official Rust 1.95 and 1.96.
Separate traced operations identify whether copy, retained-writer flush,
read-only directory flush or publication rename produces the actual errno.
The probe records observations and makes no acceptance claim.

The same job then runs the original complete `codex-hepta-fleet` library suite
through `just test`, including all five originally failing cases. It retains
failures and fresh JUnit, requires no missing or skipped cases for success, and
hashes the exact source before and after. No original assertion, access check,
readonly mode, directory ownership requirement or durability check is removed.

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** A real-platform diagnosis and
source repair, followed by current-source tests and original full CI, are required.
