# B21 collector v3: original Intel full-context failure evidence

The [original assessment](ASSESSMENT.zh-CN.md) is byte-for-byte the frozen input README. The official artifact ZIP, full job log, source archive, API/publication evidence, derived BEP, every retained attempt log/XML, compact log, fixed primary sources, and read-only verifier remain intact in the portable archive. The 42 original files plus their original freeze manifest are restored as 43 outer members. Expanded ZIP duplicates and Python cache directories are excluded exactly as the original freeze specifies.

Keep every base64 part, manifest.json and restore_packet.py in one directory, then run:

```sh
python3 restore_packet.py --output /new/empty/b21-v3-evidence --replay
```

The restorer requires Python and zstd, refuses an existing output directory, verifies every part/archive/member and the original freeze, and invokes only the read-only original evidence verifier. No product, Rust test, OS mechanism experiment, CI, ref or PR is executed or changed. Its stdout must exactly equal the original 16,908-byte root verification stdout.

Run 42164663819 / job 127718214088 failed. Actual checkout 84cc73453eb926d6f2c5b0372c0287b0ab86ed53 is the collector-only branch with the original 10,582 product leaves; it is not the PTY optimization candidate. Original collector complete=false remains unchanged: process exit 38 and test-stage BEP exit 3 differ following a recorded BES upload failure. All 501 produced attempts and 1,002 attempt log/XML files are retained; 438 target summaries, attempt totals, and Rust cases are distinct denominators. Four targets failed, including 28P/3F original PTY cases; original Core failed and timed-out attempts remain alongside their retries.

BEP is a credential-sanitized / opaque-payload-omitted derived representation, not the raw original BEP. Two successful Core retry XML files are not claimed bound to their compact XML-output digests. See qualification.json and the full assessment for these limits. B21 and B15 remain OPEN; there is no ledger transition. The input freeze remains unchanged; subsequent independent review is a separate receipt.
