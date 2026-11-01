# R16 actual channel cost confirmation

This study reuses the eight frozen R15 HX laws and all four already-fitted
one-action controllers. It changes feature execution so that each model pays
for only the features it uses. The shared owner grants every arm exactly the
same initial STOP / READ-then-STOP / REFRESH-then-STOP capability. It does not
compare one-step policies with a stronger planner or refit on confirmation.

`features.py` leaves state/confidence and ordinary-dual policies free of unused
STOP-value and first-hit calculations. Cold ordinary propagation banks are
charged to every arm; only value/risk constructs the augmented first-hit
matrix exponentials. Cold restoration, cold propagation, cold risk preparation,
warm feature computation and warm full owner execution are measured separately.
The deployment account includes current input decoding and all cold preparation.
Historical R15 fitting remains separately attributed to its original source and
host. It is neither free knowledge nor a new current-host timing measurement.

The new owner accepts an explicit feature provider. It does not modify R15 or
replace global functions. Development checks compare 768 complete query records
and their actual feature vectors against the unchanged original executor before
the new source/input freeze. Formal namespace17 is separate from development917.

`PROTOCOL.json` registers 8 fits x 2 domains x 64 worlds, four arms, paired-fit
sign-flip tests with Holm over four comparisons, a .001 utility gain minimum,
and descriptive cost reuse points. State labels, typed addresses, trained
policies and finite one-action scope retain their R15 meanings. A positive
finding would not establish a financial equity/risk dual force, general channel
necessity, continuous control optimality, or production economics.

Run from the repository root:

```sh
python -m tools.hcsn.reachable_state_r16_20261101.channel.checks
python -m tools.hcsn.reachable_state_r16_20261101.channel.campaign freeze
python -m tools.hcsn.reachable_state_r16_20261101.channel.campaign confirm --source-commit PUBLISHED_SHA --seed 151101 --domain iid --output channel_run/151101_iid
python -m tools.hcsn.reachable_state_r16_20261101.channel.statistics --input channel_run --output channel_run/SUMMARY.json
```

The exact source and eight input files must be published and read back before
formal confirmation. The runner verifies the manifest. Shards preserve complete
world tapes, public prefixes, chosen actions, actual targets/fees and timings.
Any failure preserves the current world and completed arms and invalidates the
complete-confirmation summary. Outer process receipts should meter imports and
final writes; do not add nested timer scopes to them again.
