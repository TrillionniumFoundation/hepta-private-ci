# ACT3 stage 7: isolated procedural replay and paired evaluation

**NoUpdate.** Sixteen actual GRU fits and a 640-episode paired filesystem panel
do not establish a success-rate or primitive-call advantage over fixed skills.
The fixed library remains the reference. These are research artifacts, with no
production model activation or FinalUse authorization.

## Training that actually ran

The loader verifies the original ACT2 archive at commit
`0584b3344f70ed51d9e09224e105bfa4d1a4635f` before deriving typed procedural records.
It binds each approved TRAIN record's canonical content, task identity, purpose,
split and source. A claimed source hash cannot authorize altered features or
actions. Factual-memory purpose, confirmation records, duplicate identities,
missing labels, invalid dimensions and nonfinite values are rejected.

| Quantity | Final qualified campaign |
|---|---:|
| Reused TRAIN trajectories | 80 |
| Distinct normalized feature/action sequences | 9 |
| Valid feature/action examples per epoch | 368 |
| Initialization seeds | 8 |
| Replay orders | ordered, shuffled |
| GRU fits | 16 |
| Epochs / optimizer calls per fit | 220 |
| Total optimizer calls | 3,520 |
| Target-environment primitive calls during training | 0 |
| New independent tasks | 0 |

The shuffled treatment permutes each feature together with its observed macro
action inside its original sequence. It preserves the sample set, padding mask,
initialization, model, optimizer and update budget. One permutation seed,
20261110, is frozen before fitting. Each order has 647,680 valid label
presentations across eight fits. It is not an independent dataset or a general
causal demonstration of biological replay.

All eight ordered models reproduce both the original saved tensors and entire
NPZ bytes exactly; both properties are now asserted. The training entry point
does not load confirmation trajectories/outcomes for fitting or model selection.
The original manifest contains definitions of both splits, and the overall ACT3
work has already examined ACT2 confirmation results. This is not a sealed or
blind experiment. Labels are observed macro actions, not invented terminal
success labels for UNKNOWN outcomes. Recovery-point and local-repair policy
learning are not claimed by this selection-only training campaign.

Four behavioral replay tests pass, including actual small fits while SQLite
connections and the destination constructor are denied, and rejection of changed
content retaining a valid source label. Three family-boundary tests pass,
including checkpoint corruption before any effect and preservation of physical
effects when qualification fails after publication.

## Paired filesystem result

Each arm uses the same public-observation stop guard, primitive budget and
16 previously exposed controlled probes, with eight model seeds. Version 1/2,
length 3/5, lost acknowledgement, partial precommit failure and opaque
post-effect observation are represented. There are 128 episodes per arm.

| Arm | Complete | Primitive calls | Stop overrides | False success | Duplicate effects |
|---|---:|---:|---:|---:|---:|
| Fixed skills | 96/128 | 1,600 | 0 | 0 | 0 |
| Original head | 96/128 | 1,600 | 0 | 0 | 0 |
| Original GRU | 96/128 | 1,600 | 34 | 0 | 0 |
| Ordered replay GRU | 96/128 | 1,600 | 34 | 0 | 0 |
| Shuffled replay GRU | 96/128 | 1,600 | 0 | 0 | 0 |

The 25% incomplete stratum has an opaque owner after its first effect; the
executor preserves UNKNOWN. Ordered replay and the original GRU have identical
per-task decisions, completion and effect/call counts. Shuffling removes the
observed need to correct premature stop proposals in this panel, without a
final task-quality or primitive-call benefit. The shared guard can mask policy
differences, so this result does not prove sequence context is universally useless.

The separate retained-effect auditor verifies all 640 panel identities and
2,080 physical payloads from the archived destinations. Timings and owner
requests are recorded, but no latency or total-cost advantage is qualified.
The 16 generated probe IDs still use ACT2's ten normalized observations and
three options. They add zero independent real tasks.

## Evidence and reproduction

`RESULT.json` is the compact decision record. `training.tar.xz` retains all
sixteen models, 220-loss histories, typed traces, source pins, frozen permutations,
per-fit records, full training result and checksums. `filesystem.tar.xz` retains
the complete paired panel and physical destination bytes. `ARCHIVE_INDEX.json`
binds every retained file, and `SOURCE_AND_EVIDENCE.json` binds the final local
sources and test records. Full optimizer moments are not persisted, so these
artifacts do not qualify interrupted training resumption.

```sh
python3 scripts/act2_learning/test_procedural_replay.py \
  --archive qualification/act2-learning-20261110/run2 -v
python3 scripts/act2_learning/procedural_replay.py \
  --archive qualification/act2-learning-20261110/run2 \
  --output /new/empty/path/replay
python3 scripts/act2_learning/test_family_qualification.py \
  --archive qualification/act2-learning-20261110/run2 -v
python3 scripts/act2_learning/qualify_families.py \
  --archive qualification/act2-learning-20261110/run2 \
  --replay-models /new/empty/path/replay --families filesystem \
  --output /new/empty/path/filesystem
python3 scripts/act2_learning/audit_families.py /new/empty/path/filesystem
```

The dedicated workflow performs offline training and filesystem evaluation before
installing the browser runtime. Its subsequent real-browser and mixed-family
gates are mandatory; a skipped unit fixture cannot produce browser qualification.
Local results do not imply any hosted workflow has completed.

## State of the six requested ACT directions

| Direction | Delivered evidence | Remaining gate |
|---|---|---|
| Preserve fixed skills | Fixed reference retained throughout every panel | No learned adoption |
| Skill/option contracts | Existing native contracts retained; shared legal termination, owner verification and strict continuation bindings | Production CellStateOwner/FinalUse integration; separate cancellation/compensation qualification |
| Learn selection, recovery and repair | Actual paired selection fits; diagnosed 48 original premature stops; deterministic owner reconciliation | Learned recovery-point and repair policies with grounded training labels |
| Separate procedural replay | Pinned typed TRAIN loader, exact record bindings and denied-effect checks | Production replay ownership and independent benefit |
| New families, versions and faults | Actual filesystem effects and audits; browser and mixed-family implementations | Browser/composition NOT_RUN locally; independent real tasks and open semantic changes |
| Genuine cold restoration | 64/64 paired restorations across 160 real subprocesses, preserving original failures | Cross-family cold restoration, independent trust domain, concurrency and power loss |

The native contract in
[`action_skill.rs`](../../codex-rs/hepta-automation/src/action_skill.rs) binds
initiation, policy, termination and goal digests. The trusted observer evaluates
conditions; the digest itself is not an executable predicate. Cancellation is
an observation field, not a separate contract `cancel_digest`. The
[`driver`](../../codex-rs/hepta-automation/src/action_skill_driver.rs) and
[`verified_outcome`](../../codex-rs/hepta-automation/src/action_runtime.rs) require
authoritative effect evidence; a process exit or cancellation ACK cannot prove
no effect. Compensation is a separately identified and authorized effect bound
by [`AuthorizedEffectIntent.compensation_for`](../../codex-rs/hepta-automation/src/authorized_effect.rs).
[`CellStateOwnerV1`](../../codex-rs/hepta-neuron/src/cell_types.rs) already owns
durable inference lookup, snapshots, commit and reconciliation. The research
checkpoint does not replace this production authority. Its recovery and local
repair remain deterministic protocols, rather than learned recovery policies.

Earlier immutable stages: stop diagnosis PR #5723, continuation core #5725,
process qualification #5734, filesystem #5746, browser #5748, composition #5760.
The original 4,480 diagnostic episodes reuse 80 ACT2 tasks; cold restoration
reuses four tasks. Prior and repeated filesystem runs reuse the same controlled
probe definitions. These counts must not be pooled as independent task evidence.

Actual Chromium startup fails in this environment with socket EPERM. The browser
and composition stages remain NOT_RUN, with failure evidence retained. Production
ownership, complete lifetime cost and a model benefit over fixed skills remain
open. The user's adoption gate is therefore not satisfied.
