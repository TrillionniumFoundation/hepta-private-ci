# Fresh-byte content memo: less payload SHA work, unchanged reads

One frozen saved-128 qualification reduced payload SHA-256 computations from **256 to 174**, avoiding **82 computations and 67,732 bytes of SHA input**. Every original payload path was still freshly read: **256 logical reads and 1,680,512 bytes per complete walk**, with the same state, checkpoint and expected-reference checks.

This is a deterministic work-count result, not a CPU speedup result. The savings are 32.03125% of payload SHA calls but only about 4.03% of hashed payload bytes. Python dictionary content hashing, exact byte comparisons, compilation, allocation and memory also cost resources. Input barriers, reference construction, JSON/history identity hashes and qualification checks are outside the scoped payload SHA counters. Nothing here establishes lower total CPU, lower physical disk traffic or compliance with a strict 256-step complete-method budget.

## Implementation and comparison

The isolated candidate compiles the exact original bytes_get function with its SHA dependency replaced by a per-history ContentMemo. The exact original history function, canonicalization and stage helpers are unchanged. The prior JSON-equality optimization is NOT included in this experiment.

Memo keys are the complete newly read immutable builtin bytes, not a pathname, mtime, expected digest or file-identity shortcut. Python dict lookup requires exact bytes equality on a hit, not merely a matching dictionary hash. The reused SHA digest is still compared against the current reference by original bytes_get. Length, symlink and reference checks remain. Changed bytes cannot reuse the old digest solely because their filename or length is unchanged.

Each history invocation creates a new memo. It admits at most sixteen distinct contents of at most 4,096 bytes each, with no eviction. Cached key payloads total at most 65,536 bytes, plus dictionary/object overhead; this is not a total interpreter-memory bound. The actual saved-128 walk retained sixteen 826-byte contents, totaling 13,216 bytes before cleanup. A finally block copies the statistics and clears the keys, including on refusals, so exec-generated function/global cycles do not retain payload keys pending garbage collection. Saved entry/byte statistics describe the pre-clear state.

The large 12,303-byte actor checkpoints are not cached. Repeated small order checkpoints supply the savings. This opportunity was identified from pre-run metadata: 128 order references had 24 distinct declared SHA values. The run then verified the actual bytes, not just those declarations.

## Fixed controls and negative evidence

- Original and memo each validate the entire saved 128-leaf chain with all seventeen checkpoint hashes. Their complete logical read/leaf counters are identical.
- A second invocation uses a new memo and reproduces the same work statistics. It is a cache-scope control, not a repeat selected for favorable timing.
- Both implementations reject incorrect checkpoint hashes at cursors 0, 64 and 128 with identical error and work records.
- Separate new temporary files exercise nine cases per mode: initial content, another path with identical bytes, a wrong expected digest on a cache hit, same-path changed bytes with an old reference, the new correct reference, restored original content, appended content, truncation and a symlink. Each mode accepts four cases and refuses five; returned byte hashes, errors and logical-read counters agree. The memo still rejects changed content and wrong references. Historical files are never modified.
- Capacity controls admit sixteen 4 KiB contents, refuse to retain a seventeenth, reuse the first, and do not cache repeated 4,097-byte content. Exactly 21 calls perform 20 SHA computations over 81,922 bytes with one hit. A bytearray is rejected.

The whole qualification records **9 history walks, 768 leaves, 1,552 logical payload reads and 10,083,248 bytes**. These counters are logical verifier work, not physical disk traffic. Temporary-file changes test trusted-local behavior; they are not an adversarial filesystem, concurrent-race or owner-authentication guarantee. Intermediate file mutations are evidenced by the frozen sequence and retained observations, not a complete filesystem snapshot after every write.

## Recorded process cost and retained limits

One invocation, no retry: whole-child wait4 exit 0, **0.177797 CPU seconds**, **0.179903 wall seconds**, peak RSS **12,708 KiB**. Outer CPU prefix **0.031517557 seconds** is additional, its final tail is unknown and nonzero, and preparation, independent review and prior work are additional. Receipt CPU is cost accounting only; no per-case timing screen or comparison was conducted. Its 0.177797 CPU seconds must not be compared with the earlier equality diagnostic's 0.285247 seconds as a speedup: the two workloads differ.

Limits: child 4 CPU seconds / 45 wall seconds, outer 6 CPU seconds / 60 wall seconds, 256 MiB address space and 2 MiB per file. The shared synthetic lock was checked before launch; both worker wait4 and outer shell completion were observed. OUTER_TOOL_TRANSCRIPT is an explicitly posthoc tool-response excerpt, not a second wait or prospective receipt. Transport time is not method time.

No NumPy/model import, array decoding, prediction, optimizer update, new data generation or 256-step run occurred. Old model NPZs were only read as opaque bytes. The historical 128-step engineering fixture uses six handmade rows, not natural data. Fresh full-history IO remains, and the missing strict aggregate CPU enforcement/overshoot proof remains unresolved. HOLD_NEW_TRAIN, access denials and old scientific stopping rules are unchanged. No runtime integration, old release substitution, deployment or training is authorized by this result.

## Provenance and reproduction boundary

Final freeze SHA256: 4b0653dddd7465e9740e4d723ee492db89a9587320b287bc082c4b8adcc68828.
Raw result SHA256: a10c9d466c0bbb7d982e8511979d565d370b60618d2b74ca773011da964075bc.
INPUTS binds 392 original files totaling 2,406,239 bytes; both pre/post barriers passed. SUMMARY embeds the original freeze, result and complete child receipt. Source review added explicit cache cleanup and clarified partial-failure evidence before execution; neither change was result-driven tuning.

The candidate files here are preserved byte-for-byte. This is a reviewed evidence snapshot, not a standalone portable runner: the code expects the exact original sibling `segmented-actor-validation128-candidate-v1` saved layout and existing shared lock. Original payload/model inputs are not repackaged. Independent review files bind the scope and snapshot separately. Any future integration needs separate review; do not automatically rerun the historical science or substitute this snapshot into its directories.
