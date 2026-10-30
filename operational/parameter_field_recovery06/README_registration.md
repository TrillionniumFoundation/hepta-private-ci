# Execution06 registration and nonoverlapping historical cost accounting

These modules continue the frozen execution05 adapters with narrow prospective execution06 changes; the original execution04 cost semantics remain intact. The original files and every original RAW/OPS seal remain untouched. No new scientific metric, threshold, population, action, or automatic scientific retry is introduced.

## Fixed interfaces

`registration.py` retains the `hepta.fullstudy.durable-registration-config.1` schema and its CLI. It accepts only `execution06_detached_20261030`, the fixed execution06 RAW/OPS roots, and `analysis06detached`. It additionally requires exact basic descriptors for `producer_config`, `execution04_cost_facts`, `execution05_cost_facts`, `producer_adapter_source`, and `execution05_costs_source`. The latter is the exact new `execution05_costs.py` source descriptor and is checked against the registered Git commit together with the other adapters.

The producer configuration is externally pinned and has exactly these keys:

```json
{
  "schema": "hepta.execution06.producer-config.1",
  "execution_episode": "execution06_detached_20261030",
  "producer_map": {"path": "ABSOLUTE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "import_receipt": {"path": "ABSOLUTE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "fresh_registration": {
    "execution_episode": "execution06_detached_20261030",
    "raw_root": "FIXED_EXECUTION06_RAW",
    "source_root": "ACTUAL_COMMITTED_SOURCE_ROOT",
    "registered_commit": "ACTUAL_COMMIT",
    "protocol_sha256": "ORIGINAL_PROTOCOL_SHA256",
    "runtime_sha256": "ORIGINAL_RUNTIME_BINDING_SHA256",
    "source_freeze": {"path": "ABSOLUTE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
    "profile": {"path": "ABSOLUTE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"}
  }
}
```

The placeholders above are interface documentation, not a usable registration. The initializer creates real descriptors only after independently pinned A17 ancestry has been validated and materialized into the new fresh destination.

`helpers(config)` loads the original helpers, verifies their fixed source bytes and committed adapter sources, then returns private `ProducerAdapter` namespaces. The original global modules are unchanged. The serial 4→11→14 queue extension still preserves every accepted job definition. A17 has an explicit import record and no fabricated START/PID. The other 13 jobs retain their original gates. The analysis reader is also created by the producer factory before its scoped cost check. The original 26 scientific and 30 finalization seal gates remain in place.

Finalizer registration writes `evidence_id: verification06` and `evidence_relative: evidence_v2/verification06` before bundle serialization. The finalizer factory requires that verified freeze and exact destination before invoking the original literal algorithm. No already sealed helper artifact is edited.

## Execution04 cost facts

`historical_costs.execution04_cost_plan(facts_descriptor, expected_import_receipt_descriptor)` is a read-only bounded metadata verifier. It returns verified cost metadata and actual file bindings. The facts descriptor must come from the externally pinned registration configuration. Exact top-level keys are:

```json
{
  "schema": "hepta.execution06.execution04-cost-facts.1",
  "execution_episode": "execution04_durable_20261030",
  "accounted_in_execution_episode": "execution06_detached_20261030",
  "a29_failed": {"path": "ORIGINAL_A29_FAILED_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "outer_envelope": {"path": "ORIGINAL_WAIT4_COMPLETE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "import_receipt": {"path": "ACTUAL_EXECUTION06_IMPORT_RECEIPT", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "root_io": [
    {"receipt": {"path": "ORIGINAL_ROOT_WAIT4_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"}, "scope": "independent_root_step"}
  ],
  "unknown_additional_work": true
}
```

`outer_envelope` is execution04 `wait4_launcher/WAIT4_COMPLETE.json`, not `ENVELOPE_FAILED.json`. Its original pipeline config must match the independently verified A17 import anchor. The A29 failure must have the fixed original SHA and path; only selected cost/error fields are decoded. Unselected scientific values are lexically skipped.

Each root IO row has exactly `receipt` and `scope`. `root_io: []` is valid but does not imply zero other root work. Allowed original locations are only:

- `BASE/fullstudy_execution04_ops/root_steps/<step>/WAIT4.json`
- `BASE/continuation_recovery_20261030/current_readiness_0253/root_archive_io/01_A-17/readback_steps/{000,001,002,003,004}/WAIT4.json`

Root receipt, intent, stdout, and stderr descriptors are checked. Receipt path, receipt hash, and child PID/start ticks are deduplicated; an outer supervisor child cannot be entered as independent root work. The root's preregistered independent scope identifies disjoint commands. Distinct PIDs alone are not offered as proof of arbitrary process independence. A nonzero command exit retains its actual wait4 CPU and separately discloses potentially unwaited descendants.

## Execution05 cost facts and full failed-episode provenance

The root preregisters an exact `FAILURE05_SOURCE_PINS.json` descriptor before preparing the new amendment. Only after its actual archive and remote-byte closure exist may the root call:

```python
from operational.parameter_field_recovery06.execution05_costs import validate_source_pins, build_cost_facts
validated = validate_source_pins(failure_sources_descriptor)
# After actual execution06 A17 materialization, the initializer alone calls:
cost_facts_descriptor = build_cost_facts(import_receipt_descriptor, failure_sources_descriptor)
```

`validate_source_pins` is read-only. `build_cost_facts` creates exactly one new `BASE/execution06_preregistration_inputs/EXECUTION05_COST_FACTS.json` with exclusive creation, then validates it. Existing partial or complete output is preserved; the builder does not retry. No scientific module is imported or launched.

The source-pins schema is `hepta.execution06.execution05-source-pins.1`. Its exact top-level keys are `schema`, `source_episode`, `target_episode`, `frozen_source_commit`, `roots`, `archive_manifest`, `archive_verification`, `remote_closure`, `forensics`, `forensics_measurement`, `key_receipts`, `actual_outer_wait4_missing`, and `unknown_additional_work`. The episodes are execution05 and execution06 respectively. The frozen source is execution05 C2 `7544b0a57a3b5624f3f2190449efeb84854b414d`. Both last flags must be true. All receipt values are exact basic descriptors, not content copied into a purported original receipt.

`roots` has exactly `raw`, `ops`, `cas`, `prereg`, `recovery`, and `forensics`. They bind the actual original execution05 roots beneath `BASE`; `forensics` is the `failed05_forensics` subdirectory of the original recovery root. `key_receipts` has exactly `a29_failed`, `controller_wait4`, `worker_wait4`, `primary_failed`, and `prior_import_receipt`. Each key has a fixed original source path and SHA in `execution05_costs.KNOWN`.

One unchanged `hepta.fullstudy.durable-archive-manifest.1` covers full RAW, OPS, CAS, preregistration, and recovery/forensic metadata. Every logical path maps to its actual BASE-relative source. The cost records, truncated trace and original forensic result must appear with exact sizes and hashes. The full logical-path and external-reference indexes are themselves bound and archived. The verification receipt must cover every logical file, byte, chunk and part. This is an actual failed-episode archive, not scientific completion: one A17 job and one of seventeen ACK barriers remain the recorded terminal population.

The root's `hepta.execution05.failure-archive-remote-bytes-verified.1` closure must identify actual upload/readback versions for all archive parts plus MANIFEST, VERIFIED and ARCHIVE_COST, in order. Population is derived from the manifest, not hardcoded. Each item retains distinct-file/readback/xattr evidence, actual remote identity, the matching local/readback size and hash, and a successful measured helper receipt with its exact intent/stdout/stderr. Later history checks revalidate these small immutable receipts and original cost records; they do not reopen expendable duplicate payloads, silently upload again, or claim a new remote authentication.

The original cost-only forensic result binds the cumulative failure counters and the truncated trace scan. Its 96 complete JSON lines corroborate explicit lower bounds of 16,128 scheduled/backward calls and 14,976 optimizer steps; those branch-local counts are a subset and are never added to the failure's cumulative 17,280/15,984. Gzip completion/checksum was not verified, and missing optimizer entries are not converted into observed zeros. Progress-parent counts are never used to infer gradient work. Scientific completion/head artifacts must remain absent.

The generated facts schema is `hepta.execution06.execution05-cost-facts.1`, with exactly `schema`, `execution_episode`, `accounted_in_execution_episode`, `failure_sources`, `import_receipt`, and `unknown_additional_work`. It binds the new import to the same original execution04 A17 scientific anchor and zero new imported work. The history projection includes every actual receipt/source binding, both distinct failure increments, and the explicit unknown CPU scopes.

## Accounting rules

The earlier historical gradient lower bound remains **182,096**. The literal failed execution04 A29 adds **14,784** scheduled/backward gradient calls and **13,728** optimizer steps. The separate failed execution05 A29 adds **17,280** scheduled/backward calls and **15,984** optimizer steps. The historical gradient lower bound is therefore **214,160**. Each failed A29 is a cost increment only, never a completed or independent scientific sample. The next A29 run is an entire new job; no partial-state resume is admitted. The complete planned logical study costs **343,808**, already including A17 once, giving the prospective all-attempts lower bound **557,968**. Do not add the original A17 39,168 again.

Imported A17 appears once among the current logical study's completed stage rows. It contributes zero failed-attempt increment and zero newly executed import microsteps. The original stage costs, source/profile identity, and completion bytes are not relabeled as new execution06 work.

The report retains its original current stage/endpoint ledger. A separate `nonoverlapping_cost_ledger` adds only disjoint measured intervals: those stage intervals, the failed execution04 A29 stage interval, execution04's measuring parent CPU, the explicitly declared independent root wait4 intervals, and the separate execution05 controller wait4 plus supervisor self interval. The execution04 outer wait4 CPU is retained as a **nonadditive inclusive observation containing A17**. Exclusive overhead is never inferred by subtracting unlike scopes. Execution05 contributes only controller wait4 **1,548.712305 seconds** plus supervisor self interval **7.248885367 seconds**, a disjoint measured lower bound of **1,555.961190367 seconds**. Its worker wait4 **1,512.719833 seconds** and phase CPU are nested in the controller and are not added. The actual execution05 outer wait4 is missing, not zero. Historical missing CPU, entry/cleanup/unwaited work, other root work, remote compute, and later execution06 envelope overhead remain explicitly unknown. Failure-archive construction, transfer, and recovery engineering receipts remain in the separate execution06 root engineering ledger; they are not relabeled as execution05 scientific work. The new ledger is a lower bound, not a complete campaign CPU total or an upper bound; do not add it to a later inclusive execution06 envelope.

The original historical V5 FAIL and missing-receipt tiers remain unchanged. Public-summary engineering costs remain separate from completed receipt-backed work. `apply_cost_adapter` changes only scoped cost accounting/rendering functions and restores the original functions even on failure. The numerical analysis and all scientific decision rules remain the frozen original implementation.

## Validation and source lineage

The original copied driver SHA is `19e3eedaacc7795a2b45ea8165f2aa5e8180e0d12f4fc925075384861ab32979`; the original copied cost adapter SHA is `e8ec187543e5d249142a706699156fa97db767d6f1193ec9be466359a59ad440`. These identify the preserved inputs, not the new prospective files.

Focused tests exercise actual frozen queue construction, projection of selected metadata, unchanged current ledgers, tampering and wrong-source rejection, one-time A17 accounting, retention of failed command CPU, duplicate/nested root rejection, both permitted root locations, nonfinite CPU rejection, exact configuration paths and hashes, isolated helper factories, cost functions surviving report cloning, and finalizer destination validation before IO. They use synthetic temporary fixtures and start no scientific worker. Neither execution04 nor execution05 failure metadata is used as a resume cursor. Additional failed05 tests cover source/archive omissions, missing actual outer receipt, unexpected new completion markers, malformed or missing costs, wrong A17 ownership, remote population/byte mismatch, retired duplicate readbacks, exact increment arithmetic and nested CPU exclusion. Postseal separately requires the real detached-parent lineage plus the final supervisor wait4.
