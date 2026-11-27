# HCSN visit-897 N128 scale-preservation VJP hosted evidence

This evidence-only snapshot binds Draft PR #6275 source commit
`373e7c35eb245e25fbc8ad451d3d3cf814ad6172` to its sole hosted execution:

- Actions run `43308685765`, attempt 1;
- job `131498644834`;
- artifact `13984194091`;
- original ZIP SHA256
  `a14aa34f73fb9b05f3563c0a0674df765d03d281444d47eb12e697c352c8613f`.

The original artifact contains the frozen-source binding, pre-import review,
resource preflight, execution receipt, full `RESULT.json`, `RAW.npz`, and the
unmodified controller stdout/stderr. An independent zero-execution readback
verified 10/10 directional checks, all 125 transpose coordinates, 12/12
negative guards, 42 forwards, 2 continuous adjoints, 2 backward attempts, and
0 optimizer updates. The 445-byte Torch warning remains in the original
stderr.

The result is only `PASS_LIMITED_N128_ONE_LAW`. It does not qualify N256/N512,
the full posterior or finite domain, trainable physics/support/delay/migration,
second-cycle feedback, full-network training, task benefit, C2 full replay,
HPCA external custody, production adoption, or global closure.

Global status remains **HOLD / NoUpdate / all_closed=false**.
