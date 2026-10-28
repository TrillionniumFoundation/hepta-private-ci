# Next cell structure gate

**Current result: held. No new training, held evaluation or physical-node experiment has run for this gate.** This directory freezes a prospective research protocol and provides an offline evidence validator. It does not activate cells, select a production model, change authority or claim general intelligence.

`PLAN.json` freezes the hypotheses, comparator contracts, OOD axes, resource index, retention horizon and acceptance thresholds. `FREEZE.json` binds that protocol, the validator and the preserved prior evidence. A complete **execution registration is still missing**: new candidate sources, corpora, held manifests, per-arm budgets and retained targets must be registered before training. Freezing these gate requirements is not a claim that a new experiment has already been preregistered and run.

## Evidence that remains in force

`PRIOR_EVIDENCE.json` records exact source commit, paths, byte lengths and SHA-256 identities from PR #4173 (`afa351f8d2958c99032ed127693ce81362dbd630`). Its original formal training source was `c39552216b46f1187526aef4bda073c0a9380c72`. The PR was open and unmerged when this snapshot was taken.

The formal audit passed 1,413 integrity checks. That supports the preserved evidence, not structural superiority. All three seeds rejected split and merge admission; dynamic children tied the rank-8 control at 15/16, and merge scored 14/16, 14/16 and 13/16. Learned addressing used the registered reject-all fallback. Under each router, all 2,880 parameter/retrieval pairs had equal outputs. The 64-cycle, three-seed maintenance run completed 192 cycles and passed 7,198 audit checks, with perfect recorded finite maintenance scores, but its interrupted attempt left **unbounded missing costs**. Those positive, negative and unknown outcomes remain separately visible.

The earlier study used eight fixed addresses, frozen pretrained representations and an authored typed graph. Its content learning, persistence and maintenance results do not establish new-entity/task generalization, spontaneous topology formation or physical multi-node net benefit. Existing native-agent PSS/latency results and a single-task NDU result cannot replace any required evidence here.

## Frozen comparison

Eight new seeds and three task families cover independent held expressions, new entities, new tasks and their joint shift. Each family/axis needs at least 64 functional cases, with registered diversity minima; each family also needs 64 unknown probes. Repeated query rows are not independent statistical trials.

The primary adaptive cell arm is compared with the same-information static typed graph, fixed experts and an equal-parameter monolith. An exact typed lookup arm remains a separately labelled reference. Distributed adaptive cells are additionally compared with distributed static cells and the single-node adaptive arm. Input/output contracts, available information, base assets, parameter accounting, feature/target presentations, row exposure and training/search caps must match the frozen registration. Giving cells a simpler decomposed input violates that contract.

Every registered seed/family/axis must meet coverage and error limits. Against each relevant control it must show either at least two percentage points of quality gain with no more than 5% greater bounded lifecycle cost, or quality within 0.5 percentage points with at least 10% lower bounded lifecycle cost. Candidate upper cost bounds are compared with control lower bounds. These are prospective engineering thresholds, not facts inferred from the earlier runs.

Costs include preparation, representation, search, training, selection, evaluation, serving, maintenance, migration, deletion, recovery and retention. Failed candidates, shared assets, duplicated checkpoints, source/cache bytes and monitoring gaps remain charged. The fixed index in `PLAN.json` is dimensionless and is **not a monetary price model**. Raw resource counters and global wall intervals remain visible. Unknown costs never become zero: an unobserved interval needs an evidenced finite upper bound, otherwise the result is held.

Continual retention uses at least 64 previously demonstrated capabilities over cycles 0, 1, 8, 16, 32 and 64. Their target hashes are frozen before training. Deletion separately checks access revocation, active lineage, retained ability and finite agreement with independent clean rebuilding. It does not claim that archived artifacts were erased or establish general machine unlearning. Permissions, emergency stop, source revocation and device privacy remain exact external controls.

Physical migration requires distinct machine fingerprints, non-loopback observed transport, independent inventory evidence, exact checkpoint transfer and a fresh receiver process. Process/container/node names on one machine and loopback TCP do not satisfy it. Network transfer, synchronization and recovery costs enter the same lifecycle comparison.

## Evidence pack contract

The root result manifest has schema `hepta.cell-structure.result-pack.v1`, `evidence_kind`, `plan_sha256`, `prior_evidence_sha256` and an `artifacts` list. Each descriptor contains `id`, `kind`, relative `path`, `bytes` and `sha256`. Paths must stay inside the evidence directory without symlinks. Required JSON artifacts are listed below; source code, parameter files, gradient traces, monitor logs and inventory receipts are additional byte-verified artifacts. No artifact is executed by this validator.

| Kind | Required content |
|---|---|
| `registration` | Plan/prior/source/split hashes; `registered_at_unix_ns`; immutable `contracts` keyed by `seed\|arm`; retained capability IDs and `retained_expected_sha256` |
| `source_manifest` | Nonempty `files` with artifact ID/hash; authority-control and held-evaluator source hashes |
| `split_manifest` | Training/calibration case, expression, entity and task IDs; held cases with `id`, `family`, `axis`, `known`, expression/entity/task identity and complete structured `expected` output |
| `training_receipts` | Runs keyed by seed/arm, exact registration/source hashes, contract, measured compute and every completed/failed/interrupted attempt with ID, start/finish time and optimization steps; dynamic arms also bind initial/final parameter and gradient-trace artifacts |
| `evaluation_observations` | Actual `held_first_opened_unix_ns`; one raw `{seed,arm,case_id,accepted,output}` per matrix cell. Correctness is recomputed against frozen complete outputs, including registered traces |
| `cost_ledger` | Each run's global start/finish interval and every required phase; each phase binds a measurement-source artifact, charged attempt IDs and every resource's `{lower,upper,unobserved_ns}`. Gaps additionally bind a method and evidence hash |
| `structure_trace` | Every accepted/rejected decision with seed/arm, train/calibration partition, kind, before/after graphs with materialized node parameter hashes and fresh-reader artifact hashes |
| `retention_observations` | Seed/arm/cycle/capability matrix with accepted, output and the original expected target |
| `deletion_observations` | Seed/arm runs with deleted source ID, active lineage, revoked exposure and actual/independently rebuilt retained outputs |
| `physical_host_inventory` | Physical host IDs, distinct machine fingerprints, observed non-loopback IPs and byte-verified inventory receipts |
| `migration_observations` | Seed/arm, original/destination host, registered case, identical sent/received artifact hashes, transfer completion, fresh receiver start and exact observed/expected output |
| `independent_audit` | Exact ID/hash inventory of every other artifact; empty held-access, omitted-attempt, authority-control and unexplained-monitor-gap violations |

The validator does not treat a submitted `passed` flag as evidence. File hashes establish integrity and binding, not independent truth about the physical world. The independent audit and raw collector/host evidence must be reviewed as such; hand-written passing measurements are not a real experiment. A computed pass applies only to this registered bounded scope and grants no production authority.

### Execution provenance limitation

Execution provenance is not authenticated by this validator. Evaluation rows currently carry no evaluated checkpoint or graph digest, so the validator cannot establish that their outputs came from the final training parameters or the accepted split/merge graph. Gradient, fresh-reader, resource-source and host-inventory artifacts are byte-verified; their contents are not independently executed or authenticated here. `passed_registered_scope` therefore means that the submitted evidence pack satisfies the offline consistency and numerical checks. It is not authenticated evidence of actual structural benefit. Such a claim additionally requires binding the evaluated checkpoint and graph to the observed execution, and independent review of the raw training, resource, physical-host and audit evidence. Those execution and audit requirements remain outstanding for this gate.

## Run

```bash
python -m unittest -v test_validate.py
python validate.py CURRENT_RESULT.json --output CURRENT_VERDICT.json
```

The second command intentionally exits **3** for the current held result. Exit 0 means the submitted pack passed the offline checks for the registered scope, subject to the execution-provenance limitation above; 1 means measured gates failed; 2 means malformed/mismatched evidence; 3 means evidence is missing, unknown or held. Synthetic unit fixtures always remain held and cannot publish a structural claim. A new protocol version must preserve this freeze and prior outcomes rather than retune thresholds against new held results.
