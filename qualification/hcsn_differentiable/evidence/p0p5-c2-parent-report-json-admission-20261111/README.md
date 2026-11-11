# P0/P2: digest-bound parent report semantic admission (HOLD)

This is an **isolated successor source fix**, not a restart/replay of the
original C2 job and not a scientific result. On the preceding exact
`cec5f9ec172f0338d1869bb4cba85f99925ee5b6` head, the new five
synthetic adversarial tests exposed a fail-open path: the successor's
terminal-result gate SHA-pinned the original parent `result.json` but
parsed it with permissive `json.loads`, following symlinks and accepting
duplicate keys, NaN, float overflow and oversized content.

The fix applies the **same bounded strict semantic JSON contract** already
required for the newly produced terminal file to the digest-bound parent
report. It parses the exact bytes checked against the recorded size and
SHA-256, rejects nonregular/symlink/oversized parent files, validates
the top-level object and rereads identity after parsing. Parent and
child CPU/wall measurements remain visible on rejection.

## Raw native red and green

- Exact-parent **RED** on desktop system Python 3.12.3:
  `1a1ccbf6128-2564-1050`, 11 tests, 5 assertions failed, exit 1.
- Corrected isolated gate **GREEN**:
  `1a1ccc03bfc-2564-1053`, 11/11 PASS, exit 0.
- Unchanged system interpreter could not run the whole successor suite:
  `1a1ccc150a3-2564-1058`, 11 PASS + 4 import errors
  (Torch absent), exit 1; preserved rather than hidden.
- Pinned existing desktop Python 3.12.3 / Torch 2.8.0+cu128:
  `1a1ccc2de7a-2564-105e`, **43/43 PASS**, no errors,
  no skipped tests, exit 0.

All four original stderr/stdout logs and native exit receipts are copied
unchanged into this directory. `EVIDENCE.json` binds their SHA-256,
the exact code/test bytes, numerator and denominator. No fixture count
is reinterpreted as all-six C2 training, independent replay, P1 accuracy,
P2 matched baselines, P3 boundary value, P4 multimodal benefit, or P5 adoption.

**HOLD_NO_GO**: all P0-P5 admission gates remain open. Source-head CI
and full-repository CI on this new branch must be evaluated independently.
