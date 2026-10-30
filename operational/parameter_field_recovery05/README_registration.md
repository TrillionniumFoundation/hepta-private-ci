# Execution05 registration and nonoverlapping historical cost accounting

These new modules are mechanical copies of the frozen execution04 driver and cost adapter, with narrow prospective changes. The original files and every original RAW/OPS seal remain untouched. No new scientific metric, threshold, population, action, or automatic scientific retry is introduced.

## Fixed interfaces

`registration.py` retains the `hepta.fullstudy.durable-registration-config.1` schema and its CLI. It accepts only `execution05_backpressure_20261030`, the fixed execution05 RAW/OPS roots, and `analysis05backpressure`. It additionally requires exact basic descriptors for `producer_config`, `execution04_cost_facts`, and `producer_adapter_source`.

The producer configuration is externally pinned and has exactly these keys:

```json
{
  "schema": "hepta.execution05.producer-config.1",
  "execution_episode": "execution05_backpressure_20261030",
  "producer_map": {"path": "ABSOLUTE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "import_receipt": {"path": "ABSOLUTE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "fresh_registration": {
    "execution_episode": "execution05_backpressure_20261030",
    "raw_root": "FIXED_EXECUTION05_RAW",
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

Finalizer registration writes `evidence_id: verification05` and `evidence_relative: evidence_v2/verification05` before bundle serialization. The finalizer factory requires that verified freeze and exact destination before invoking the original literal algorithm. No already sealed helper artifact is edited.

## Execution04 cost facts

`historical_costs.execution04_cost_plan(facts_descriptor, expected_import_receipt_descriptor)` is a read-only bounded metadata verifier. It returns verified cost metadata and actual file bindings. The facts descriptor must come from the externally pinned registration configuration. Exact top-level keys are:

```json
{
  "schema": "hepta.execution05.execution04-cost-facts.1",
  "execution_episode": "execution04_durable_20261030",
  "accounted_in_execution_episode": "execution05_backpressure_20261030",
  "a29_failed": {"path": "ORIGINAL_A29_FAILED_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "outer_envelope": {"path": "ORIGINAL_WAIT4_COMPLETE_PATH", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
  "import_receipt": {"path": "ACTUAL_EXECUTION05_IMPORT_RECEIPT", "bytes": 0, "sha256": "EXTERNAL_SHA256"},
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

## Accounting rules

The earlier historical gradient lower bound remains **182,096**. The literal failed execution04 A29 adds **14,784** scheduled gradient microsteps, with **13,728** optimizer steps and its original stage CPU/wall interval. The resulting historical gradient lower bound is **196,880**. The failed A29 is a cost increment only; it is never counted as a completed or independent scientific sample, and the next A29 run is an entire new job rather than a resume.

Imported A17 appears once among the current logical study's completed stage rows. It contributes zero failed-attempt increment and zero newly executed import microsteps. The original stage costs, source/profile identity, and completion bytes are not relabeled as new execution05 work.

The report retains its original current stage/endpoint ledger. A separate `nonoverlapping_cost_ledger` adds only disjoint measured intervals: those stage intervals, the failed A29 stage interval, execution04's measuring parent CPU, and the explicitly declared independent root wait4 intervals. The execution04 outer wait4 CPU is retained as a **nonadditive inclusive observation containing A17**. Exclusive overhead is never inferred by subtracting unlike scopes. Historical missing CPU, A29 entry/cleanup/unwaited work, other root work, remote compute, and later execution05 envelope overhead remain explicitly unknown. The new ledger is a lower bound, not a complete campaign CPU total or an upper bound; do not add it to a later inclusive execution05 envelope.

The original historical V5 FAIL and missing-receipt tiers remain unchanged. Public-summary engineering costs remain separate from completed receipt-backed work. `apply_cost_adapter` changes only scoped cost accounting/rendering functions and restores the original functions even on failure. The numerical analysis and all scientific decision rules remain the frozen original implementation.

## Validation and source lineage

The original copied driver SHA is `19e3eedaacc7795a2b45ea8165f2aa5e8180e0d12f4fc925075384861ab32979`; the original copied cost adapter SHA is `e8ec187543e5d249142a706699156fa97db767d6f1193ec9be466359a59ad440`. These identify the preserved inputs, not the new prospective files.

Focused tests exercise actual frozen queue construction, projection of selected metadata, unchanged current ledgers, tampering and wrong-source rejection, one-time A17 accounting, retention of failed command CPU, duplicate/nested root rejection, both permitted root locations, nonfinite CPU rejection, exact configuration paths and hashes, isolated helper factories, cost functions surviving report cloning, and finalizer destination validation before IO. They use synthetic temporary fixtures and start no scientific worker. The execution04 failure metadata is never used as a resume cursor.
