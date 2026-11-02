# Continuous task adapter qualification result

Published source/artifact freeze: `2b4345b80c1c2773e961915522df32c77675685e`.
Prepared freeze SHA256: `a890bc9a383bc9c407c9c2a6bc35541544e6e438b3b0ce72fd83e4f1c86a3c1d`.
Raw evidence SHA256: `42d69f15af7806d74adecaf561941c6ee4971a832b6b43e69ac5ec60a79dc866`.

All 505 action-boundary restores exactly matched uninterrupted suffix decisions
and final checkpoint in every non-timing field, across 40 fresh qualification
worlds and 80 episodes using five archived FPT heads. All source, old-model and
opt-in artifact hashes also matched at execution end. The archived heads were
not retrained, and these worlds were isolated from the control campaign.

Original episodes made 118 due source-access attempts: 112 successful FullHX
read completions and six failures. Every-boundary suffix replays made 324
additional attempts: 308 successes and 16 failures. Thus actual qualification
execution totaled 442 attempts and 420 successful completions. Original episodes
requested READ 121 times; three requests were cancelled or remained uncompleted
at terminal selection, so requests must not be equated with completed reads.

Original episodes contained 24 resolved events, 14 releases, and two intervals
with at least two events. Their checkpoints included 65 pending-request states
and 29 refractory states. All these states were included in the action-boundary
replay comparison. The complete local hit/release times are in every original
and resumed raw trajectory, with public logical elapsed time separately present
in the Owner receipts.

Measured execution (including generation, original episodes and replay checks)
took 11.081745329 wall seconds and 5.585728181 process CPU seconds. Frozen FullHX
setup, separately recorded, took .012260009 wall seconds and .005352444 CPU
seconds. These measurements make no speed or cost-advantage claim.

Raw trajectories, every replay, exact checkpoints and cohort file digests are
in `evidence/continuous_task_prepared_final2/qualification/RAW.json.gz` (619,245
bytes); generated world/public/evaluator/packet files remain under the same
qualification directory. `SUMMARY.json` is the frozen runner output;
`COUNTS.json` is a reproducible post-run count extraction. Run
`continuous_task_counts.py PATH_TO_RAW_JSON_GZ` to verify the latter.

This closes the declared **same-process serializable action-boundary adapter
qualification**. It does not establish cold-process or mid-action recovery,
Rust parity, complete gradients, task benefit, retraining suitability, energy
savings, or production qualification. Continuous truncated resets and real-x
features remain an explicitly opted-in change from the archived finite process.
