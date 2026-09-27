# utility.ndu exact A–D qualification request

Candidate branch: `work/utility-ndu-abcd-convergence-20260928`. Freeze `SOURCE_SHA`
and the fetched `BASE_SHA` before executing. `BASE_SHA` must be an ancestor of the
source candidate for this convergence; concurrent updates are conflicts, never
force-pushed. Each source-head checkout must equal `SOURCE_SHA`. Each synthetic
checkout must equal the deterministic commit with parents `[BASE_SHA,SOURCE_SHA]`
and tree from `git merge-tree --write-tree BASE_SHA SOURCE_SHA`. Synthetic commit
identity intentionally differs from source-head identity; do not call that drift.

Independently execute `source`, `core`, `callers`, `product`, `lint`, `host` in both
lanes. Every command must execute and return zero, including strict Clippy, native
property/fixture tests, actual Agentd process/UDS tests, named-host measurements
and real ENOSPC/EROFS fault cuts. Empty tests, retries, skips, historical logs and
self-reported source cleanliness cannot substitute. Preserve failed-suite logs.

After staging changes regenerate `IMPLEMENTATION_MAP.json` with
`python3 scripts/hepta_ndu_map_integrity.py --rebind-index --candidate-branch
work/utility-ndu-abcd-convergence-20260928 --baseline-main BASE_SHA`. Verify the
committed closed-world map against the exact commit/tree. Source cannot embed its
own eventual Git SHA: runtime receipts bind the final identities and the map
binds the complete staged source-object inventory.

Each retained suite directory contains a closed-world SHA-256 manifest. Download,
verify and aggregate all twelve on the trusted producer workflow. Reopen the
raw named-host and mounted-filesystem records, including observed workloads,
latency thresholds and recovery phases; do not trust summary flags or hashes
alone. Publish
`ndu-qualified-evidence-SOURCE_SHA` only after every suite actually passes.
AWS/KMS/versioned readback is a separate manual protected-environment step; its
receipt is not inferred from successful GitHub artifact upload.

Production activation remains false. External actor-data authenticity, protected
clock/CAS provider enrollment, named target filesystem/power-loss acceptance,
encrypted production backup/restore/retention drills and stochastic acceptance
are separate deployment evidence, not configurable success booleans.
