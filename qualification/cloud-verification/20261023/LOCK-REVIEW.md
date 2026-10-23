# Preserved #3582 lock-only review and remote proof

Parent: `46dc890e40cf5bb7057012e4de756eab73c21351`.
Published lock-only child: `2f7ae91c4176896d0b9caf9aea75ed3e030a81f8`.
Tree: `ae67bf0e3de0feede6a9ed13ad5fb4e034517f30`.

Primary cloud engineering review: the one-line replacement `"sha2"` → `"sha2 0.10.9"` is in codex-execution-core's lock entry. Workspace Cargo.toml requires sha2="0.10"; Cargo.lock contains both 0.10.9 and 0.11.0, and execution-core had the only ambiguous unversioned reference. No dependency upgrade or resolved package record changed. Locked check failed before, then passed for execution-core/contracts/operations. Bazel 9 mod deps --lockfile_mode=update exited 0 with no MODULE.bazel.lock change. This initial lock review was the primary engineer's review, not misattributed to the later independent review agent.

GitHub plugin update_file returned Cargo.lock blob `a6e0ce83788e19f54bc4598b37585ca4714b5f99`. Plugin fetch_file at the exact child returned the same blob and the disambiguated line. Local Git hash matched; SHA256 of the complete lock was `8f538ae5ce68a767480ba784ebd81c3dec306bbd50a1910c5ef120e7ea2fcb6b`. Fetched child parent/tree were checked, and `git diff --exit-code 2f7ae91c4176896d0b9caf9aea75ed3e030a81f8 --` against the validated lock-only candidate was empty. The only changed file was Cargo.lock (+1/-1).

The 191-test and strict-Clippy failures were recorded openly in #3582, not claimed passed. The subsequent independently reviewed source repairs are in #3586. Original commands, failures and patch accompany this file. Neither draft was merged or deployed.
