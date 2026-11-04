# Independent original evidence replay, 4 November 2026

These are independent read-only checks of existing Actions artifacts. Product heads were not changed and product tests were not rerun by the verifier. All original failed results remain failed. This checkpoint does not admit the complete dependency union or production.

## Memory source 230d2d69a8c68ae6f8c502118fd9a8ee33027c37

All three original ZIP sizes, SHA-256 digests, CRCs, receipt output hashes and 126 declared source inputs per lane were independently checked against immutable Git bytes. The before and after input maps match.

Linux and macOS each executed the original full Memory target with 272 passed tests and the same seven originally ignored qualification probes. Their original Clippy targets also passed. The macOS eleven-failure predecessor is retained in the earlier checkpoint and is not substituted for this result. Windows executed all four original batches: 256 passed, four failed and seven originally ignored. The batch filters partition the full Windows suite; nested subprocess cases do not enlarge the denominator. The four recovery failures and their exact original diagnostics remain in memory-230d-windows.json.

The two peer static reviews are anchored by their existing Git blob IDs in manifest.json. Neither review claims a native execution. The 4751 review is bound to candidate 8dfdf8c2fb146e8d47a943e7270851224eafa532 and does not transfer the 230d result to that candidate.

## Robrix source 767f069c96a6cd2735b3a4166799a1de79017d25

All four original ZIPs were verified. The three native lanes each bind 108 immutable source inputs. Linux and macOS completed both original cases with no failed, ignored, measured or filtered cases, plus the original Clippy target. The actual lock lane binds 1,658 Git inputs and 13 outputs: committed-first check, original update and post-update check each returned zero; the generated, committed and Git MODULE.bazel.lock bytes match (1,701,389 bytes, SHA-256 1a58f7d1fcbfe850d18a01c19faf15c941dfd229cb8caeb406dbe8ce8c99522e).

Windows remains failed. Its original Bazel command returned zero, but the command output, test.log and test.xml all contain only the writer case after “running 2 tests”; no second case or final Rust summary exists. The XML has one Bazel wrapper case and repeats the incomplete output. It cannot establish two successful Rust cases. The absence is already present in the original command output, so copying the report afterwards is not sufficient to explain it. The cause of the incomplete execution/output remains to be determined.

The saved Windows test.log and test.xml are byte-identical to the original artifact members, independently rehashed. The file ending .decoded.txt is the timestamp-stripped Actions rendering of command stdout; line endings were normalized by log transport, so it is expressly not the original byte stream. The original 86,591-byte stdout remains in artifact 13287169410 with SHA-256 aba860f51c17a0ce4845db90c247e364191565ba63280ff0cae50e4b9292e965. It is referenced by the original ZIP digest and receipt. No original ZIP member was overwritten.

Each JSON here is the parsed compact verifier output with the full verifier-report digest and run/job identity. It is not represented as the full report with that digest. Full reports and original ZIPs are retained by the immutable bridge runs; the verifier source is already committed and rerunnable.
