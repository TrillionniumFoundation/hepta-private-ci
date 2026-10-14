# Paired physical Stem / Cell resource frontier (development)

P1/P2 strong-control acceptance boundary over the EXISTING concrete Encoder and
Head training paths, packing/replay and ridge consolidation. Do not confuse
parameter-count planning with RSS, actual FLOPs or measured energy.

\`paired_frontier.audit\` consumes all task-level, same-input, same-source-group
outcomes and per-arm **isolated-process** model residency/peak RSS,
training/inference work and wall time. It rejects nonpaired denominators,
dropped failures/abstentions, mismatched source families, fabricated metrics,
an arm pretending shared-process memory is standalone peak RSS and baseline
substitution. Unknown work or energy stays null, never zero or an imputed saving.

The strong empirical rule is no loss of observed correct counts **within every
source group**, plus all measured resource dimensions no worse and at least one
strictly improved. This is a stringent exploratory Pareto diagnostic, NOT a
confidence bound, independent reviewer signature, model selection or guaranteed
old-task retention. The minimum independent source-family threshold is recorded,
but repetition/seed count is not used to manufacture independence. Publication,
future windows and runtime promotion remain outside this module.

The existing concrete data producers in \`execution.py\`, \`head_batch.py\`,
\`feature_replay.py\`, \`consolidation_study.py\`, and
\`ridge_consolidation.py\` remain responsible for real material. They cannot
fill absent 421M replicated-model or complete hardware/energy observations
with synthetic guesses. All tests use unmistakable fixtures only.

Run \`python -m unittest -v experiments.shared_stem_cell.test_paired_frontier\`.

## Actual process-lifetime peak visibility

On Linux, `execution.run`, `media_execution.run` and `consolidation_study.study`
now report `process_lifetime_peak_rss_bytes` from the kernel `ru_maxrss`
high-water value (KiB converted to bytes), or null when unavailable. This
includes model loads, candidates, import overhead and the process history;
`peak_is_isolated_per_*_arm` stays false. An isolated **per-arm** RSS number
still requires a fresh, one-arm-per-process run; it cannot be inferred by
subtracting endpoints or assigning the whole-run peak to each Head. Sensor
energy remains null absent a real sensor. The `process_peak.py` unit tests
check Linux units and unknown-platform/failure handling.
