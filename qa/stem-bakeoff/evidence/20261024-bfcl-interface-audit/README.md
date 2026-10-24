# BFCL adapter prerequisite audit, no model evaluation

Read INTERFACE_AUDIT.md for the result and limitations. This package contains metadata and audit tools, not the original task text, initial-state values, ground-truth trajectories, model outputs or the upstream implementation files.

## Reproduction

Obtain the fifteen official files named by upstream-manifest.json and extra-source-manifest.json from https://github.com/ShishirPatil/gorilla at exact commit 6ea57973c7a6097fd7c5915698c54c17c5b1b6c8. Place each file under input/ using its basename, preserving its bytes. Total size1,372,382 bytes. The scripts verify sizes/Git blob hashes before processing. No automatic downloader or package installation is included.

Run, from this directory:

    python audit.py
    python group_risks.py
    python verify_sources.py

Python standard library only. The scripts read JSON and parse Python AST; they do not import/execute upstream code or run models/tasks. They regenerate metadata files in this directory. Save published metadata before running if a separate comparison is wanted. These tools do not fetch private Hepta dependencies.

The independent review in observed/source/verification.json independently checked all variants, not just base rows, and found the same192 conservative components. observed/source/verify.py is preserved historical review source, not a portable package command: it retains sibling workspace paths and additionally requires the official recursive tree snapshot, the original inspected Hepta baseline and source-review note. Those are not bundled. Its result does not substitute for obtaining original inputs and rerunning the audit.

The Hepta limitation refers only to local cell-feature-snapshot-profile/baseline.py with SHA256 56f88a126c1e0e55cd1b17db81bdce9ab205d0f6ea1196f71144235cd8d38e4d. It does not assert that every newer Hepta profile lacks these capabilities. No production compatibility or safety claim follows.

## License and lineage

Upstream Gorilla code/data metadata is Apache2.0; LICENSE.upstream retains its license. Original paths and Git blob hashes are included. Interface schemas are metadata derived from those official files. The package does not republish the600 task definitions or three source implementations.

No split, new semantic labels, training, model scoring, full task execution or CI was performed. All600 variants belong to200 base groups; repeated states/paths create192 conservative connected components. Zero exact Hepta function mappings were verified. Six annotated path names require reconciliation with current tool schema/executor before any adapter generates labels. Source-observer boundaries must exclude privileged path/future-turn/hidden-state information.

Next step is a genuine schema-preserving observer/adapter design, not training on fabricated action labels. These public historical tasks cannot replace private production future-window evidence.
