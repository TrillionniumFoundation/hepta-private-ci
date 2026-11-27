# Complete original Matrix cipher target evidence

Source 3b9f69f612c18d04f00e63ea77d9a04f5aa08371 changes only code generation
for matrix-sdk-store-encryption in the current Cargo and Bazel graph. The
original PBKDF2-HMAC-SHA256 work remains 200000 rounds and the storage deadline
remains five seconds. Test methods, fixtures, rejection checks, package version,
Cargo.lock and MODULE.bazel.lock are unchanged. Original current-matrix timeout
logs remain in the normal ancestors.

Actual macOS: original just test -p codex-hepta-matrix-sdk passed all 33 tests
with zero skipped in 2.187 seconds (236.840 seconds including compilation).
Legacy upgrade and wrong-passphrase preservation completed in 0.477 and 0.433
seconds. Complete raw output and all tracked source identities are retained.

Actual Windows: run 46045325693, job 140663027973, source exact 3b9f69f.
Both full original Bazel targets ran with --nocache_test_results.
The SDK unit target passed in 48.0 seconds and storage_upgrade in 3.4 seconds.
The actual original workflow guard reported retries=0 and flaky=0; independent
full raw scanning and target-count checks agree. This is two complete targets,
not a claim about unprinted individual Windows case counts.

The complete 276144-byte job log and original artifact 15222811607 are saved.
The 2597202-byte ZIP digest, CRC and every original member were independently
verified. Original just fmt, bazel-lock-update, and lock check all returned zero;
both locks retained their exact original hashes.

This evidence closes these SDK targets. The full Bazel matrix remains separate;
the original Windows sandbox consumer failures and token delete boundary remain
open and are never converted into passes by this qualification.
