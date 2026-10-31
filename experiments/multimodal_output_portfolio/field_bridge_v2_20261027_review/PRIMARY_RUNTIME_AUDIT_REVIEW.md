# Independent audit of the nine primary runtime fitting banks

All nine completed training/development runtime profiles pass the independent
audit: seeds 17, 29, and 43, each with frozen, ordinary, and field checkpoints.
This closes the consistency audit of these fitting artifacts. It establishes
neither a held-out controller benefit nor retention, and reads no primary,
audit-observer, or retention outcome rows.

## What was checked

The verifier reconstructs source-pair indices, seeded target swaps, target
pixels, and labels directly from the reserved source corpus. It renders the
retained token arrays independently, parses their complete grammar, and
recomputes the five weighted loss terms from retained uint8 pixels and the
frozen reward observer. It preserves the original 512- or 256-example
condition/action groups and separate left/right observer calls. No scientific
reward-scoring or controller-fitting helper is called to perform this audit.

It checks checkpoint-file and full-model identities against the completed
training records, including local parameter inventories, frozen base hashes,
and the original source-model identity. All 35 scientific source hashes also
remain unchanged after the audit. Every fitting input file is hashed before
and after verification, and every selected controller matches the combined
runtime completion record.

For features, the verifier independently constructs common train-only
normalization, the original history features, fixed Fourier features and
their train-only normalization, and the training-variance native coordinate
selection. It calls the pinned original kernel through its bounded C ABI to
reproduce each native feature matrix. All state calls retain `DENY_ALL` and
require calibration. Persisted features and recorded hashes match exactly.

For every head, an independent augmented least-squares solve checks the
stored ridge coefficients. Stored and independently computed predictions
produce exactly the same actions on every training and development row.
The verifier also reconstructs regression MSE, means, condition breakdowns,
regrets, all 24 candidate indices per representation, first-index tie breaks,
the selected complete controllers, fixed-action references, and the absence
of a silently added fixed fallback.

| Check | Verified result |
|---|---:|
| Completed runtime profiles | 9 |
| Hard action returns recomputed | 138,240 |
| Exact transformed feature matrices | 288 |
| Independently checked ridge heads | 432 |
| Exact individual action comparisons | 1,327,104 |
| Maximum hard-return difference | 2.220446049250313e-16 |
| Maximum coefficient difference | 4.205465478634984e-8 |
| Maximum prediction difference | 2.3323277531517306e-7 |
| Maximum stored-head normal-equation residual | 3.025957262536849e-11 |

Coefficient and prediction comparisons used predeclared absolute tolerances
of 1e-6 and 2e-6 respectively, reflecting different numerical solution methods
for regularized, correlated feature matrices. Exact action agreement was
required separately and has zero disagreements. The tiny hard-return
difference arises from independent floating arithmetic and is below the
fixed 1e-12 scoring tolerance; it is not reported as bitwise score equality.

## Work counts and their boundary

The audit independently checks the following original bank-generation and
fitting counts across the nine profiles. They are example-level work counts,
not FLOPs, energy, or wall-time savings.

| Original study work | Count |
|---|---:|
| Encoder examples | 27,648 |
| Transition examples, including common preview transition | 138,240 |
| Decoder examples, including previews and every offline branch | 193,536 |
| Reward-observer digit examples, including public previews | 387,072 |
| Offline non-stop final continuations | 110,592 |
| Offline scored action rows | 138,240 |
| Original native fitting ticks | 221,184 |

The independent audit additionally uses 276,480 reward-observer digit examples
and 221,184 native replay ticks, plus independent coefficient solves. These
are verification expenses, not treatment work or evidence of efficiency.
The summed profile audit wall time on this shared host was 44.47 seconds.

The verifier does not regenerate all model previews and final images from
scratch. Its complete reward/feature/readout audit is conditional on the
retained hard arrays and public observation banks, with their file and model
provenance checked. Independent deployment-media and chosen-action replay is
a separate audit owned by the primary evaluation reviewer.

## Verifier contract and preservation

The small verifier test covers four analytic reward cases, exact independent
target reconstruction under all four conditions, 48 synthetic heads and 32
synthetic feature matrices. Six corruption guards reject malformed token
width, changed native features, coefficients, training normalizers, recorded
actions, and selected controllers. The emitted decoder sequence has width
eight: BOS followed by seven generated tokens. An initial auditor-only
width-seven assertion was corrected from the frozen decoder source before
the real label audit; no scientific source or bank was changed.

Full result: [PRIMARY_RUNTIME_AUDIT.json](PRIMARY_RUNTIME_AUDIT.json).
Verifier contract: [PRIMARY_RUNTIME_AUDIT_CONTRACT.json](PRIMARY_RUNTIME_AUDIT_CONTRACT.json).

Full result SHA-256:
`173193a0a987bd73cb5573c8f7450e77379942024312f53ff81c6249f3d23f9e`.

Auditor source SHA-256:
`1b141a3f75bb62be4a040d21fc06338105c0185237f6e2b6d901483caf61ab01`.
