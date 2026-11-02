# Independent audit

Run from the repository root:

```sh
python -m tools.hcsn.digital_read_followup_20261101.independent_audit \
  --model-dir tools/hcsn/digital_read_before_20261031/checkpoints \
  --out tools/hcsn/digital_read_followup_20261101/evidence/independent_audit.json
```

This audit uses no hidden labels, no original confirmation episodes, and no
checkpoint selection. It traverses 310 legal states of a separately constructed
public task schedule. The model diagnostic deterministically takes 104 of those
states and evaluates every exported latent coordinate. These are diagnostic
states, **not a sample of any policy's visitation distribution**.

Across all 25 archived models, 35,880 head outputs produced 1,083 different
argmax actions when only the terminal identities were imposed. The largest
STOP deviation from zero was 0.087306; the largest SUBMIT deviation from the
model's own belief was 0.441029. This verifies an actual structural mismatch in
the old predictions. It does not establish that mismatch as the sole cause of
the original efficacy failure. On this diagnostic state set, the five-fit mean
teacher regret decreases slightly for four cell families but increases for raw
history from 0.066896 to 0.077499. Terminal consistency alone does not guarantee
better actions or task utility.

Independent task checks reconstruct the Bellman one-step expectation, verify
that sunk fees are not deducted again, and check pending cancellation. The
maximum errors were 1.11e-16, 1.55e-15, and zero respectively. The actual new
head optimizer's gradient was checked against central finite differences at
62 coordinates, including the belief-to-terminal chain and masked actions;
the largest absolute error was 1.11e-10. A zero learning rate was used for that
check, so it produced no trained model.

The separate continuous branch has its own standalone entry point, with no
dependency on the control campaign:

```sh
python -m tools.hcsn.digital_read_followup_20261101.continuous_independent_audit \
  --out tools/hcsn/digital_read_followup_20261101/continuous_independent_audit.json
```

One hundred continuous-law cases check the competing flux against a time
derivative of its CDF, with maximum absolute error 2.60e-8. Survival plus exit
mass differs from one by at most 6.67e-16 in those cases. Checkpoint roundtrip
and invalid-input RNG atomicity pass. These are finite numerical checks, not a
proof for the full parameter envelope or an autodiff qualification.

The continuous reference and the head-repair experiment remain separate. The
latter retains the old finite tables; the former uses a declared continuous
truncated reset law instead of the archived folded finite-bin reset. Therefore
no result here establishes a learned continuous-core task advantage, complete
parameter gradients, energy savings, or production readiness.
