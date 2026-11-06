# Sealed v2 experiment protocols

These JSON files are the original write-once experimental protocol envelopes
registered at commit `9a0b16a620b4203093268a2a917f76bb99eb61ef`. They specify
the controller development and distillation panels, including the original
acceptance rules and costs. Moving them into this directory distinguishes
experimental inputs from the repository's canonical development documentation.

| Current file | Original registration filename |
| --- | --- |
| `controller_v2_development.json` | `development_plan_v2.json` |
| `controller_v2_distillation_development.json` | `development_plan_distillation_v2.json` |

The migration preserves every JSON byte, its Git blob identity, and its sealed
`plan_sha256`. Historical source receipts and archived analysis outputs retain
their original names. The diagnostics reader maps those identities to the
current paths before checking the original byte digests; it keeps the original
identifiers in new summary output as well. Relabeling a historical receipt or
changing a migrated protocol remains an error.

The migration inventory and compatibility checks are recorded in
`qualification/ndu-ci-repairs-20261106/protocols/` at the repository root.
No study outcome, statistical engine, threshold, or admission rule changes.
