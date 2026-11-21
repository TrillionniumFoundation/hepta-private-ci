# N256 runtime identity admission originals — admitted receipt

This evidence-only branch preserves all four attempts under the one frozen identity `hcsn-n256-runtime-identity-admission-20261121-c6bc-001`.

- attempt 1: run 44910798387 / job 136865986747 — RED during receipt publication; 0 candidate execution
- attempt 2: run 44910947077 / job 136866426687 — RED during receipt publication; 0 candidate execution
- attempt 3: run 44911092060 / job 136866866262 — workflow success, explicit admission rejection caused by the guard using raw RECORD bytes rather than the oracle's text-decoded identity algorithm; 0 candidate execution
- attempt 4: run 44911605026 / job 136868429440 — workflow success after the guard exactly matched the oracle's measurement algorithm; admission true and candidate execution still false

Attempt 4 artifact 14710107556 is 1,182 bytes with SHA-256 `8906773cf69dbb1ec841e735b3d2f2fce2a5b23b627e10676c402bac025aeb28`. All ten frozen comparisons are true, mismatch_fields is empty, and no numerical module was imported.

All four attempts executed 0 model, 0 dynamic step, 0 expm, 0 Torch call, and 0 optimizer step. This closes only exact runtime admission. It does not rerun #6890 or confer N256 numerical, full-state, finite-domain, C2, HPCA, or production qualification. The #6890 665/69728 RED, all OOM/cancelled/UNKNOWN records, C2 full replay 0/6, HPCA NoUpdate, global HOLD, and all_closed=false remain.
