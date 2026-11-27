# Localization v2: repaired numerical law and executed real-model interfaces

**75 native mechanism tests, four original numerical fixtures, and the new
0.2-second frozen-physics profile passed. Six real model interfaces each
completed three independent initializations, for 18 interface fits and 72
optimizer updates. Formal comparative fits remain zero.** This directory keeps
the underlying successes, failures, inputs and source identities. It is not a
model ranking or a repository-wide CI-pass declaration.

The [current scope page](../../CURRENT.md) explains the mathematical definitions
and remaining gates. [STATUS.json](STATUS.json) is a reporting snapshot;
[MANIFEST.json](MANIFEST.json) gives the exact bytes of every published member.
Original records are copied without rewriting their paths, dates, status or
source manifests. Later explanatory reports are labeled separately.

## Numerical source and evidence

| Record | What it establishes |
| --- | --- |
| [Math publication inventory](math/PUBLICATION.md) | Full inventory, measured gates, precision and claim limits |
| [Failed attempt 001](math/attempt-001/result.json) | The unchanged 0.2-second profile reached a negative refined cell probability and failed |
| [Negative-bin diagnosis](math/attempt-001/negative-bin-diagnostic.json) | Independent 80-digit reference identifies cancellation in subtraction of rounded tails |
| [Repair explanation](math/repair-v2/REPAIR.md) | Direct reflected interval probability, no clipping or row renormalization |
| [Exact repair patch](math/stable-intervals.patch) | Two modified source files and one new four-test regression module |
| [Repaired source capsule](math/repair-source.zip) | Exact 29-file source snapshot used by the native qualification |
| [75-test receipt](math/attempt-002/qualification.json) | Actual native CPU FP64 tests, source before/after hashes and outcome |
| [Original four-fixture budget](math/attempt-002/original-four-fixture-budget.json) | The repair preserved the original fixture gates |
| [New profile result](math/attempt-002/v2/result.json) | All 325 gap interfaces, locked gap values, refinement anchors and unconditioned sequences passed their stated gates |
| [Native provenance](math/repair-v2/native-provenance.json) | Exact profile, source, runner, job and terminal status identities |

The repaired source capsule SHA256 is
`cb49a5f1aa24e15e25f46dd9fc8722de8fba4fa471d69a52142d37e8d98c3a2a`.
The 75-test receipt SHA256 is
`9610040fd99f9501ba4d1cfc047517101d0142bfa3994073a68b797d59c5df34`.
The new numerical result SHA256 is
`1c31a015de53ad720bfa7ac3e952fdbe494a8251161f5741c49239b247a53ddc`.
These are newly executed, source-bound receipts for the repaired snapshot;
26 source files and the original 71 tests have explicitly recorded inheritance.

This is a new fixed model with `d=0.2`, not inherited `d=0.1` qualification.
The probability repair changes numerical evaluation, not the declared model,
physics, grid, source windows or pass thresholds. Its row-wise perpetual-value
diagnostic reaches 1.6974% under the common infinity-norm scale. Passing the
common prior does not certify arbitrary initial states, observation-filtered
posteriors, trainable physics or long contexts. Refinement sensitivities and
rounded-residual estimates are not certified additive error bounds.

## Real interfaces, raw checkpoints, and independent audit

Read [AUDIT.md](interfaces/AUDIT.md) for the complete execution/accounting
explanation. The [unaltered full archive](interfaces/interface-001-evidence.zip)
is **4,103,593 bytes**, SHA256
`f32b15255a0a5cfa083d2db3b020b60d3945aeed3ca851da6f4fe8c0b4077fd0`.
It contains the complete original output inventory, including 90 checkpoints,
18 saved logits records, optimizer-step events, the exact source capsule,
data/frontend/features and audit files. ZIP integrity, every member hash and
the complete archive hash were verified. The extraction-relative `evidence/`
links below are readable copies of selected archive members; they do not
replace or modify the archive.

| Readable record | Scope |
| --- | --- |
| [Suite](interfaces/evidence/interface-001/suite.json) | All 18 arm/seed outcomes, actual capacities, rows, source hashes and costs |
| [Native execution](interfaces/evidence/interface-001-execution.json) | Completed interface driver, actual 175.057531-second wall time and unchanged source |
| [528-check independent audit](interfaces/evidence/interface-001-audit/native-audit.json) | Real tensor changes, 90 checkpoints, distinct initialization identities, dependency hashes and unchanged frozen physics |
| [Final 36-file read](interfaces/all-source-audit.json) | Live source still equals the locked capsule; no model forwards or training |
| [Metrics pipeline](interfaces/metrics-pipeline.json) | ACC/NLL/Brier/ECE recomputed from saved logits; no model ranking |
| [Data/label/gap audit](interfaces/abc-gap-audit.json) | Actual subject/sequence counts and the fixed windows' label degeneracy |
| [Successful dependency recovery](interfaces/dependency-recovery-002.json) | Verified official PLIF wheel and S4 checkout after the retained initial Git timeout |
| [Transfer verification](interfaces/transfer-verification.json) | Fixed-version chunks, complete ZIP, all member hashes and CRC |

The tiny interfaces have unequal trainable capacities: GRU 427, CfC 807,
recurrent PLIF 176, S4D-Lin 335, causal Transformer 1,179 and HCSN 9,804. The
A01 training fragment has two labels; the D01 development fragment has only
walking. Eight of 12 PLIF training windows have zero spikes. These findings
prevent interpreting the measurements as adequate SNN training, fairness,
generalization or model superiority. The three fresh training seeds are real,
but neither events nor episodes are additional independently trained models.

The original timestamps and fixed windows were retained. The entire public
dataset, including E, was read for schema, clock and global-gap metadata before
choosing the 0.2-second delay. E was not fitted, tuned on or scored by a model.
The later ABC-only audit independently finds the same 0.162175-second maximum
gap; it does not retroactively make the original selection ABC-only. The old
v1 guard failure remains unchanged in the earlier evidence directory.

The archived source's protocol predates the final audit. If its short wording
about E or outstanding source-read status is less precise, this actual-access
history and the source-bound raw records govern the interpretation; the source
archive itself is never silently corrected.

## Formal-study readiness and costs

[FORMAL_GAPS.md](interfaces/FORMAL_GAPS.md) explains the concrete implementation,
numerical, training and resource conditions that still separate this interface
execution from the requested fair comparison. It gives a prospective minimum
discriminating pilot and stopping rules; no such pilot is reported as executed.
The user has already authorized research. Missing authorization is not the
reason formal fits remain zero.

The [cost-scaling scenario](interfaces/cost-scaling-scenario.json) uses observed
training-phase times and exact subject event counts to expose the scale of the
full recipe. It is not measured steady throughput, a reliable 256-event timing
forecast, a resource allocation, or evidence of comparative efficiency.
Persistent state, p99, steady throughput, peak VRAM and complete energy remain
explicitly unmeasured. Setup, failures, numerical qualification and transfer
must remain visible in any later all-attempt cost ledger.

## Source, publishing and hosted CI are separate claims

Applied mathematical-core Python and the six interface-stage files match their
executed source capsules exactly. Reproduction and publishing helpers have
separate source identities and execution records. The new
`CURRENT.md`, updated package README and this evidence index are later reporting
files; they are not misrepresented as part of the earlier native source
manifest. The historical [first evidence snapshot](../math-closure-20261108/README.md)
retains the first 64-cell failure, 71-test run, clock diagnostics and unexecuted
Colab qualification attempt. Colab cleanup is still unconfirmed after its
recorded account-manager state failure.

The [publication records](publication/FILE_MAP.json) retain actual native Mac
transport failures, rate-limit diagnostics, transfer and publishing outcomes.
They grant no scientific pass credit. Native `gh` identity and its existing
credential channel were preserved; no main change, merge or frozen-campaign
rewrite is part of the research stack.

The hosted HCSN workflow discovers the current tests and runs the four original
fixtures on its exact checked-out event tree. The new 0.2-second profile and
real interfaces remain separately identified native results. Read actual
hosted run/head/tree records before assigning hosted CI status. A dedicated
science pass cannot be substituted for repository-wide required contexts.
