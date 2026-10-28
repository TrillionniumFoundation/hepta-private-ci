# V5: baseline gate and guard transaction experiment

This study follows the failed V4 qualification without changing its decision,
historical criteria, or source allocation. It tests two concrete mechanisms on
already disclosed V3 development sources: falling back to the selected strong
ordinary action when predicted advantage is insufficient, and reducing guard
transactions from 48 to 8 microsteps while retaining a 48-step decision interval.

## Registration and scope

`PROTOCOL.json` fixes 3 model seeds, 4 paired schedules, 6 methods and 72 training
paths. Each path consumes 288 physical gradient microsteps. The selected V3
field/richer heads, V4 origin mapping, original models, adapter capacity, SGD,
training objective, source roles and both endpoint observers remain fixed.
The ordinary baseline pays no unused feature measurement cost. This is matched
gradient work, not equal total computation.

Only the six already disclosed development roles are used. All 72 training
paths must pass a source-bound seal before endpoint evaluation begins. No new
holdout, former audit/primary/retention role, new head fit, candidate revision,
or scientific retry is authorized by this protocol. Descriptive comparisons
and the fixed `development_entry` rule are not independent confirmation.

Every executed gate has `certificate=false`. The old empirical OOF threshold
is not a uniform error bound. Seed 17's old label continuation uses action 1
while its strong ordinary baseline uses action 2. The smaller transaction grain
changes the transition kernel. These limitations are substantive and are
explained with explicit counterexamples in `THEORY_AND_PROTOCOL_REVIEW.md`.

## Reviewable source stages

1. `calibration.py` replays saved OOF heads and derives a shared empirical gate.
2. `policy_improvement_tests.py` records sufficient mathematical conditions and
   counterexamples to broader claims.
3. `transactions.py` retains accepted prefixes and rolls back a rejected current
   slice; `records.py` supplies forward hash chains and exact phase seals.
4. `run.py` executes the fixed census, preserving failures and actual work.
5. `audit.py` independently validates stored identities, states, schedules,
   work counters, emitted bytes, paired endpoints and development entry.

Each stage is committed before any new study model call. `SOURCE_FREEZE.json`
then binds the registered source commit and all imported source/input hashes;
it is external to the hashed inventory to avoid a circular digest.

## Execution

Use Python 3.12, NumPy 2.3.5 and CPU PyTorch 2.8.0+cpu. The runner fixes two
Torch threads, one interop thread and deterministic algorithms. Restore the
nine pinned original assets with their original SHA256 identities first.

From the repository root, run each seed (17, 29, 43) with:

```bash
python -m experiments.multimodal_output_portfolio.field_bridge_v5_20261027.run train \
  --seed 17 --assets /absolute/assets/original --out /absolute/v5_run \
  --freeze /absolute/SOURCE_FREEZE.json
```

Only after all training phases seal, run the same command with `evaluate` for
each seed. Then run the independent artifact audit:

```bash
python -m experiments.multimodal_output_portfolio.field_bridge_v5_20261027.audit \
  --run-root /absolute/v5_run --freeze /absolute/SOURCE_FREEZE.json \
  --output /absolute/AUDIT.json
```

Phase directories are created exclusively. Failed output is preserved; reruns
cannot overwrite it. A failed integrity audit or development entry never
authorizes access to a fresh holdout. Historical B01–B10 identities and gates,
`DENY_ALL`, `requires_calibration=true`, and `native_owner_integration=false`
remain in force.
