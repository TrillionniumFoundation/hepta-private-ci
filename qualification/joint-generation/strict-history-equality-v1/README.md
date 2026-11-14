# Saved 128 fresh-history comparison: a small, mixed timing result

The fixed diagnostic passed its correctness and local aggregate timing screen. Replacing two JSON canonical-serialization equality checks with strict structural comparison produced 59.854436 ms versus the original's 64.000860 ms across four fixed blocks: ratio 0.935213, 4.146424 ms less CPU (6.48%). **Two individual blocks were slower and two faster.** Ratios in order were 1.321029, 0.797426, 1.003951 and 0.750117. This single short measurement is not evidence of stable speedup, statistical significance, whole-controller improvement or a 256-step budget guarantee. No extra repetitions, settings or retries were selected after seeing the result. The eight timed walks cluster around 12/16/20 ms and eight short negative-call samples are 0 ns. This raises a measurement-granularity/noise concern; zero samples do not mean zero work. The 4.146 ms summed difference is not a reliable performance claim.

## What was implemented and checked

A standalone helper preserves the original canonical JSON comparison on the frozen saved 128 workload: strict int/bool/float types, finite floats, signed zero, lists and string-key dictionaries. Unequal strings or differing dictionary-key sets fall back to the original canonical serialization, preserving its ensure_ascii astral/surrogate-pair behavior. Recursion exhaustion falls back after unwinding to the canonical implementation. These two corner cases were found in source review and fixed BEFORE the sole run; they were not failed scientific runs or post-result tuning.

The worker extracts the original ActorSegments.history and bytes_get functions and four original stage helpers with AST, without importing model or dataset modules. Exactly two inequality sites are replaced. Boundary SHA hashing, state and reference checks, full fresh history walks and every opaque payload-byte/hash read remain unchanged. There is no cross-call cache or filesystem-metadata shortcut.

Qualifications retained:
- 676 literal pair comparisons, including Unicode aliases, subnormal/maximum-finite floats, a large integer and nested type distinctions.
- 128 saved equal state pairs, 256 altered counter/type pairs, six nonfinite refusals and one depth 450 pair.
- Original/candidate complete 128 positive walks with all 17 boundary hashes.
- Six negative call-state/boundary cases in both implementations. These do not mutate historical files and are NOT a disk-tampering qualification. The altered tip test reaches the history-reference comparison; the altered loss test reaches the state comparison.
- Four prespecified AB/BA timing blocks. Exact original/candidate work-counter parity is required throughout; all rejection messages match.

The fixed 22 calls record 18 history walks, 1,668 leaves, 3,328 fresh payload reads and 21,846,656 payload bytes. Four invalid job/cursor calls reject before the walk counter. These counters describe logical bytes requested by the verifier, not physical disk traffic. Timing followed the qualification calls and input verification, so it is not a cold-cache benchmark. No NumPy/model import, array deserialization, Actor construction, prediction, optimizer update or new data generation occurred. Opaque old NPZ bytes were read only to verify their original hashes. The historical 128 engineering fixture uses six handmade rows; this is not a natural-data result.

## Costs and limitations

Sole invocation: complete wait4 exit 0; child CPU 0.285247 s, wall 0.286643 s, peak RSS 14,400 KiB. Outer CPU prefix 0.041751895 s is additional, its final tail is unknown/nonzero, and preparation/review/history costs are additional. Limits were child 4 CPU seconds / 45 wall seconds, outer 6 CPU seconds / 60 wall seconds, 256 MiB address space and 2 MiB per file. The shared synthetic lock was checked before launch and held by the worker; the outer command also completed before release was reported. Per-process limits do not establish a strict aggregate method budget. OUTER_TOOL_TRANSCRIPT records a clearly posthoc excerpt of the tool response showing shell exit 0; it is not a second wait4 or a prospective receipt, and transport timing is not method timing.

The pre-run 5% summed-CPU screen passed, but short-block timing variation is material. The main quadratic fresh-file validation cost is retained. This diagnostic neither runs 256 nor resolves its missing complete-subtree enforcement/overshoot proof. HOLD_NEW_TRAIN, dataset/access denials, original failures and scientific stopping rules remain unchanged. No old source/release or live runtime was changed. This is not a production security guarantee or permission to deploy the helper.

## Provenance and portability

Freeze SHA256: 5a1a726f3db9e892b72aea9941413a8544a37244d276b5f827c3891825ceb8ab.
Raw result SHA256: a36315f00ee8b453afd2711c5d29adaff725074f46e09b015c62ffda710a1806.
INPUTS binds 392 original files totaling 2,406,239 bytes; both pre/post barriers passed. SUMMARY embeds the exact original result, freeze and wait4 receipt. Independent source/saved review is attached separately when complete.

This evidence snapshot preserves the candidate code verbatim. Its runner is NOT a standalone portable test: it expects the original sibling `segmented-actor-validation128-candidate-v1` saved 128 layout and existing shared lock. The original payload/model files are not repackaged here, no restricted resources are included, and no automatic rerun is authorized by publication. Do not substitute the evidence snapshot into historical execution directories or claim current runtime integration.
