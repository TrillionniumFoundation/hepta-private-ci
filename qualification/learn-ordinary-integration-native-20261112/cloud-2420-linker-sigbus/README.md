# Original 2420 cloud linker failure

On UID 1000 in cloud executor `74d784910ce8`, the frozen ordinary Agentd / Protocol / Ledger library test command exited 101 after 4,027.004742 seconds. Source `2420fb01d7d26d7c851f48dd24ad2f9385272259`, tree `24c507b1536b4dd7d92a87525f1adf13fa455b54`, stayed clean and unchanged. The test command started at 2026-11-12 08:54:54 UTC and completed at 10:02:01 UTC.

The original diagnostic is `collect2: fatal error: ld terminated with signal 7 [Bus error]`, with a rust-lld / LLVM 22.1 stack trace while linking the Agentd library test binary. No test was executed and no fresh JUnit was produced. This is a linker failure, not a test timeout. The log does not by itself establish ENOSPC or OOM as its cause. The exact 78,778-byte ordinary log has SHA-256 `d3f5944f3e5fb1aadf2354d81ccde0c8ea30fc9752950966422e0585d11e5763`.

The original driver, command manifest, complete log, final driver state, and successful helper verification after the failed build are retained. The completed original helper build and pre-test verification are preserved separately in `../cloud-2420-helpers-completed/`. No profile override was introduced for this attempt. A subsequent execution with a different debug profile or host is a distinct attempt and cannot retroactively pass this one.

Complete positive / NoUpdate / daemon-plus-Root cold-restart counts remain 0 / 0 / 0.
