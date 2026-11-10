# ACT3 stage 1: diagnose premature learned termination

The fixed skill library remains the reference. No model is promoted.

## Measured result

The pinned ACT2 archive is `0584b3344f70ed51d9e09224e105bfa4d1a4635f`.
The new diagnostic verifies the complete archived task/seed/arm panel, original
source ZIP, sixteen checkpoints and all required input hashes before executing.
All 640 original GRU episodes reproduce their archived decisions, features,
completion, success, duplicate counts and primitive-call counts exactly.

| Retrospective arm | Complete / episodes | Primitive calls | Stop overrides |
|---|---:|---:|---:|
| Original GRU | 464 / 640 | 6,000 | 0 |
| Reset recurrence every decision | 456 / 640 | 8,328 | 0 |
| Shared guard, fixed workflow | 512 / 640 | 6,144 | 0 |
| Shared guard, macro | 512 / 640 | 6,144 | 0 |
| Shared guard, flat (same implementation as workflow) | 512 / 640 | 6,144 | 0 |
| Shared guard, head | 512 / 640 | 6,144 | 0 |
| Shared guard, GRU | 512 / 640 | 6,144 | 48 |

The 48 extra original GRU failures occur in seeds 704 and 707 (24 each), on 32
distinct task IDs. Each prematurely stops on a readable incomplete goal before
budget exhaustion. The final fresh read prevents false success but the original
executor ends the episode anyway. The new guard rejects this stop suggestion and
uses the already available deterministic macro continuation. All five labels
receive the same guard. A genuinely unreadable destination still ends UNKNOWN.

Zero false successes and zero duplicate effects were observed in this diagnostic.
That is a finite controlled result, not a universal guarantee. The 4,480 executed
episodes reuse the original 80 tasks; **new independent tasks = 0**. No training
was performed, and no confirmation label was used by the guard. It only uses the
already public observation and read-failure count. This is a termination-contract
repair and a post-hoc mechanistic probe, not learned-policy improvement.

Resetting all recurrent state is not a valid repair: it damages other seeds and
increases calls. The guarded GRU only ties the fixed reference and still pays
inference overhead. `promotion=false`, fixed reference retained, `NoUpdate`.

## Reproduce and audit

```sh
python3 -m unittest discover -s scripts/act2_learning -p test_diagnose.py -v
python3 scripts/act2_learning/diagnose.py \
  --archive qualification/act2-learning-20261110/run2 \
  --output /new/empty/path/diagnostic.json
```

`diagnostic.json` retains per-seed summaries, all paired regressions, conditional
action probabilities and artifact/source identities. `SOURCE_AND_EVIDENCE.json`
binds the actual local files, five behavioral tests and owning formatter record.
The dedicated ACT3 workflow separately qualifies its exact GitHub source; no old
ACT2 or native production CI pass is transferred to this source.

## Existing native boundary

`ActionSkillContractV1`, `GoalCheckedActionSkillDriver`, `AuthorizedEffectIntent`
and `CellStateOwnerV1` already supply native contracts, original-identity
reconciliation, separate compensation and durable state ownership. This Python
study does not grant FinalUse, replace those owners, or activate a product model.
The subsequent stages must qualify neural state recovery and actual new tool
adapters with their own evidence.
