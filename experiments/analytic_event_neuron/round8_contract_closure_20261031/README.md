# Hepta event-contract, learning and native execution closure

This directory carries out the five requested tracks on the pinned Round7 task:
matched event contracts; content/control diagnosis; complete successors and
gradients; real READ/STOP execution; measured cost reduction and Rust recovery.

The main decision is to retain these operators as a qualified research path.
The experiments do not establish an additional net task benefit for the
first-passage cell over strong ordinary control. Stable Brownian kernels,
complete finite-process gradients, a real native implementation and a verified
broker-lifecycle optimization are concrete deliverables.

## Read the results

- [Report](REPORT.md): results, decisions, limitations and implications for Hepta.
- [Main protocol](PROTOCOL.json) and [source/candidate freeze](FREEZE.json).
- [Independent scientific and statistical review](FINAL_INDEPENDENT_REVIEW.md).
- [Kernel contract](KERNEL_CONTRACT.md), [control contract](CONTROL_CONTRACT.md),
  and [native contract and costs](NATIVE_CONTRACT.md).
- [Full-cell joint-training protocol](JOINT_PROTOCOL.json) and
  [joint-training results](JOINT_REPORT.md), separately registered after the
  primary confirmation. They do not replace its outcomes.
- [Reproduction](REPRODUCE.md), including restoration of all raw records.

## Main evidence

| Track | Execution | Main evidence |
| --- | --- | --- |
| Common content/readout, different event contracts | 90 exact cases; 15 anchors, three contracts, two declared process laws | `evidence/contract_exchange_v1/summary.json` |
| Fixed-cell calibration | 20 fits, two 400-update stages; 60 retained checkpoints | `evidence/calibration_summary.json`, `evidence/calibration_models/` |
| Complete cell/content/readout learning | 20 fits, 600 full-gradient updates; 40 frozen checkpoints; 2,560 paired trajectories | `JOINT_REPORT.md`, `evidence/full_joint_v1/SUMMARY.json` |
| Analytic and full-successor checks | Independent density/flux integration, extreme tails, complete paths and finite differences | `evidence/kernel_audit.json`, `evidence/kernel_range_audit.json` |
| Fresh primary confirmation | 46,080 trajectories, 36 arms, five fits, two regimes; zero operational failures | `evidence/confirmation_analysis.json`, `evidence/heldout_exact.json` |
| Independent deployment audit | 159,462 external transitions and 25,877 heldout internal transitions replayed | `evidence/final_independent_audit.json`, `evidence/final_policy_dp_parity.json` |
| Actual Rust model port | 480 broker executions; 225 real cold-recovery pairs | `evidence/native_validation01/REPORT.json` |
| Cost reduction | The same 240 executions; all actions/final states/artifacts equal | `evidence/native_cost01/REPORT.json`, `evidence/native_reuse_cost01/REPORT.json` |

There are 640 independent external worlds per primary regime, reused by the
36 arms. The 46,080 records are not 46,080 independent worlds. The five original
fits remain the fit-level units. The registered fit-block intervals and the
post-confirmation conditional world-sampling diagnosis are both retained.

The additional full-cell experiment was registered after the main results had
been inspected. All 40 initial/final checkpoints were published before its
four new heldout configurations were evaluated. Every family's mean nominal
soft-policy return improved, but every family's new heldout mean declined.
The first-passage final heldout soft return was 0.000280 below direct control;
the greedy difference was -0.000971. These are descriptive results from the
fixed 30-update budget, not architecture-wide bounds.

## Version boundaries

`r7-finite-v1` is the actual qualified Rust kernel: projected Gaussian, clocked
Gaussian, or absorbing upwind finite CTMC with the original tick recovery law.
Its exactness is for that finite model. The known continuous-OU approximation
error is not removed by porting it correctly.

`r8-brownian-images-v1` is the separately implemented Python constant-drift
Brownian law with stable analytic killed-bin and exit probabilities. Every
Brownian comparison jointly sets leak to zero. It retains voltage projection
and tick-end release. It does not implement continuous regenerative firing or
an exact killed OU diffusion.

The Gaussian/probit endpoint control propagates an unbounded Gaussian state.
Its nonlinear mean readout uses a declared quadrature order. The Gaussian and
probit arms are algebraically identical controls, not independent models.

## Source and delivery

The baseline is `1bbf9712140ec388f7fb7967fa7b22244386441d`. Original Round7 files
and checkpoints are unchanged. The primary source and all sixty candidates
were published at `96270fb1c3d153f0fe48c996d6f7b0b4cede34ef` before fresh
confirmation. The immutable freeze SHA256 is
`f4edffc4451697fd543bdf0e10dc7242297c13f38f8c96d21bc8d7c68355988e`.

The raw archive is lossless: 8,724 files, 99 verified binary parts, and an
independent clean-directory restoration. It includes full trajectories,
calibration targets/traces, native journals and actual broker input/output
files. Readable summaries and all candidate JSON files are also committed
directly. The qualified Linux native executables have their own small verified
bundle and portable restoration entry point.

Full-cell joint-training records are committed directly in
`evidence/full_joint_v1/`: every initial/final checkpoint, every update's full
gradient, training curves, exact evaluations and compressed paired trajectories.
They are separate from the immutable 99-part primary raw archive.
