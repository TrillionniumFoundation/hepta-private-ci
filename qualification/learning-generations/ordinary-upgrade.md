# Ordinary qualification and exact-task installation

`hepta-cognitive-upgrade` composes the original file evaluation owner, independent
selector, artifact CURRENT owner, Agentd TaskFlow/FinalUse owner and signed
Supervisor release owner. It has no signing key, replacement journal, mutable
model slot or Chain-derived activation authority. Its commands are:

```text
hepta-cognitive-upgrade qualify|inspect|publish|revoke|advance FLEET_ROOT INPUT_SHA256 < input.json
```

`INPUT_SHA256` covers the actual stdin bytes. Referenced material files have their
own byte digests. The input types are in `cognitive_qualification_wire.rs`,
`cognitive_upgrade_plan.rs` and `cognitive_artifact_owner_materials.rs` under
`codex-rs/hepta-agentd/src`. The bounded raw process fields remain in the
`cognitive_process_*` modules; these are materials that original owners validate,
not serialized opaque qualification or authority tokens.

## First acquisition and ordinary operator handoff

The external host file pins the Agent, predecessor model/readback, source release,
selection policy, current learning verifier, original holdout binding/fence and
independently retained anchor. It also specifies `future_not_before_unix_micros`.
Its digest is part of the original frozen estimand. Trust, artifact-owner and
holdout paths must be outside the Agent's workspace, home and run roots.

The operator supplies the full cross-fold plan, metric roles and sources, native
candidate/baseline temporal plans and exact sealed holdout-material manifest.
Every stage reuses those same inputs:

| `qualify` stage | Original boundary and next material |
| --- | --- |
| `plan_statement` | Freeze the complete host-bound plan and emit the original Generator signing payload. No holdout use or signature is invented. |
| `reserve` | Verify the Generator and consume one exact timed reservation through the original fenced, fsynced file owner. Return its original record/use/head and actual local reservation time. |
| `acknowledgement_statement` | Build the canonical statement for an independent Observer's receipt of that durable ACK. A caller-supplied receipt time has no authority until that Observer signs it. |
| `observer_statement` | Require the already recorded timed reservation and signed ACK; release exact collected inputs under the original holdout callback, run the original estimator, and emit the window Observer payload. |
| `evaluator_statement` | Verify the window Observer and emit the original Evaluator payload derived from native metrics. |
| `finalize` | Revalidate current signatures and persist the original qualification. Optional selection handoffs are `candidate_binding_statement`, `selector_statement`, then `admit`, using the original evaluator binding, dataset/ledger verification and independent selector. |

The original owner samples the first reservation clock itself. The first call
after the pinned future boundary fails before a new reservation. If persistence
finishes too late, its consumed history remains; a failed reply cannot invent an
earlier ACK. Replay preserves the first exact record and time. Older untimed
records remain byte-compatible, but cannot be promoted into this fresh timed
protocol. Replaying a timed process descriptor always requires its ACK; removing
the optional descriptor field cannot select the older untimed behavior.

The ACK and future windows must use the same currently trusted Observer. The
observer attests when it received the durable ACK; this is an external evidence
assumption, not a clock oracle created by the CLI. ACK receipt precedes the pinned
boundary and every actual window. ACK validity is checked again at publication.

Timed input rows use Unix microseconds. The shared native gate joins exact final
window IDs, unique decision IDs, candidate/baseline outcome bijections, actual
decision/outcome times and row counts. It also requires this final-window source
cut, with no automatic replacement of the submitted value:

```text
SHA256("hepta.agentd.timed-final-cohort.v1\0"
       || frozen_plan.plan_digest[32]
       || frozen_plan.final_holdout_digest[32]
       || canonical_inputs_length_u64_big_endian
       || serde_json::to_vec(TemporalComparisonInputsV1Raw::from(inputs)))
```

This is the native wire's reconstructed field and array order, not arbitrary
input JSON whitespace. Changing any row, order, plan or material requires a new
matching Observer statement. The cut binds exact content. Upstream completeness
of offered/pending/censored populations and independently operated custody still
require evidence from the actual source owners. In this study the estimator uses
the final cohort; the first window is separate signed time/source evidence.

An original persisted `Ineligible` decision produces `no_update`; an original
`InsufficientEvidence` decision retains that distinction. The actual Supervisor
release and running ranker must still match the pinned predecessor, otherwise the
result is `blocked`. Invalid signatures, corrupt history or unavailable CURRENT
are failures, not evidence of a harmless no-update. An eligible qualification
alone does not publish, select or install a model.

## Exact Chain task and signed service transition

Register immutable Agentd source/target releases through the original Fleet
catalog. The target release arguments pin both the absolute bootstrap descriptor
and its byte digest. `inspect` replays the original evaluator, selector and CURRENT
reader and returns a `CognitiveUpgradeCommitmentV1` plus its output SHA-256. The
commitment includes exact Agent/release/launch/descriptor/model/predecessor
identities and the local observation timestamp. Its domain is
`hepta.agentd.cognitive-upgrade-task-output.v1\0`, followed by the ordered compact
serde JSON for that typed commitment.

Use that output in the specified Chain task's original reserve → provider receipt
→ owner acceptance transaction sequence (tags 2, 4 and 5). The existing host-pinned
PoN provider config must bind the actual Chain executable/hash, node namespace,
version profiles, depth/work policy and signed provider contract. The exact
acceptance packet is the original TaskFlow effect payload, separately covered by
its FinalUse grant and provider key. Packet SHA is not part of the output
commitment, so this order does not create a hash cycle.

`advance` resumes the original durable effect, including Unknown/restart recovery.
It requires the specified task/owner/provider/output to be accepted in that exact
active packet under the original depth/work policy. Every returned Chain authority
flag remains false. The signed Supervisor grant remains mandatory and binds the
actual original `control_revision`, lifecycle generation and supervisor epoch.
The read-only status field is optional for older responses: missing is not zero
and cannot be used as a signing input.

`Installed` requires the original committed release transaction and the actual
new Agentd ranker readback, with Chain reobserved after that readback. A later
reorg reports `blocked`; it does not issue a rollback or new grant. Unavailable
candidate data fails before installation. Durable dataset withdrawals are read
by the original CURRENT/ranker/FinalUse path. Its initialized namespace rejects
missing/corrupt/pending or conflicting withdrawal history; it does not claim to
resist an administrator rolling back an entire trusted persistent namespace.

## Retained native scenarios and exact inputs

Use the existing build/test commands and retain the exact source, binary hash,
compiler and build receipt. Direct libtest execution uses the original study
wrapper, which preserves its 600-second limit and failed output:

```text
python3 qualification/learning-generations/run_study.py --scenario ordinary-future --binary ABS_AGENTD_LIBTEST --output FRESH_DIRECTORY
python3 qualification/learning-generations/run_study.py --scenario ordinary-upgrade --binary ABS_AGENTD_LIBTEST --output ANOTHER_FRESH_DIRECTORY
```

The two selectors are respectively
`cognitive_ranker::tests::three_generation_learning::ordinary::actual_ordinary_cli_reserves_future_qualifies_selects_and_replays`
and
`cognitive_ranker::tests::three_generation_learning::ordinary_upgrade::actual_ordinary_cli_chain_task_supervisor_upgrade_and_no_update`.
Both are explicitly ignored by default; the wrapper selects exactly one ignored
native test. A zero-match filter is not a successful run.

`ordinary-upgrade` requires these explicit executable/hash pairs:

| Executable variable | SHA-256 variable |
| --- | --- |
| `HEPTA_PON_NODE_BINARY` | `HEPTA_PON_NODE_BINARY_SHA256` |
| `HEPTA_PON_TASK_FIXTURE_BINARY` | `HEPTA_PON_TASK_FIXTURE_BINARY_SHA256` |
| `HEPTA_SUPERVISORD_BINARY` | `HEPTA_SUPERVISORD_BINARY_SHA256` |

The Chain build must include the original `hepta_task_fixture` example and
`trnm-pon-node`. The fixture creates a fresh development namespace and admits only
reserve/receipt; real Agentd submits acceptance. This scenario uses the existing
`authenticated-v1` development backend without `--operator-task-*` inputs. It does
not exercise or enable the restricted external operator task owner, whose
authenticated-backend combination the original Chain CLI rejects. The Supervisor
binary uses the existing explicit `production-authority` build feature in this isolated namespace;
default release builds and production authorities are unchanged. The same-source
Agentd and ordinary CLI binaries are resolved by `codex_utils_cargo_bin`; explicitly
pin `CARGO_BIN_EXE_codex_hepta_agentd` and `CARGO_BIN_EXE_hepta_cognitive_upgrade`
when invoking a libtest binary directly. Agentd starts its real embedded AppServer.
No standalone Codex CLI or HTTP provider mock substitutes for that service/Chain
path. If host sandbox/readiness rules prevent it, preserve the failure.

`ordinary-future` performs first timed acquisition and raw bootstrap reconstruction
without claiming a service installation. `ordinary-upgrade` exercises real source
launch 5 → target launch 9, exact task reconciliation across that process change,
signed release installation, actual reorg/recovery, missing data and revocation.
Its additional 32 newly offered application tasks enter the original
`LedgerWriter`: actual Agentd context → durable decision → current revalidation →
independent role execution/outcome → complete offered cohort dataset freeze.
Those tasks are an execution check, not an independent statistical qualification.

Only a separate, newly reserved post-install final cohort that passes the original
native qualification while actual model readbacks remain identical increments the
study's `observed_qualified_update_count`. A plain `Installed` observation leaves
that counter null. The following equal candidate exercises ordinary no-update.
Every CLI invocation retains input/output/error hashes, identity, wall times and
monotonic elapsed time; failed observations and cleanup remain part of the run.
All keys and arithmetic tasks here share one administrator, so organizational
independence and general neural-model efficacy remain explicitly false. These
scenarios are executable protocol evidence only after the corresponding native
receipt passes, not unattended production-learning qualification.
