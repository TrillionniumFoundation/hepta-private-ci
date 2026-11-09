# VERIFY-1 native engineering result

Scientific acceptance: **HOLD**. Production authority: **NONE**.

The raw native archive includes the original tested source, logs, frozen roster, SQLite databases and all experiment records.

| Scope | Observed result |
| --- | --- |
| Native unit tests | 48 passed, zero skips |
| All planned attempts | 120/120 |
| Confirmation trajectories | 96 |
| Actual effect subprocess calls | 336 |

| Policy | Accepted / attempted | Accepted errors | Detected injected faults | Mean detection delay (steps) |
| --- | --- | --- | --- | --- |
| deterministic_rules | 8 / 24 | 0 | 20 / 20 | 1.4 |
| external_each_step | 8 / 24 | 0 | 20 / 20 | 0.0 |
| fixed_check_time | 8 / 24 | 0 | 20 / 20 | 0.8 |
| historical_frequency | 8 / 24 | 0 | 20 / 20 | 0.0 |

These are descriptive fixture measurements. Fault families repeat a two-field SQLite task; source group counts do not establish independent real-task sample size.

Every arm retains mandatory host checks. Zero accepted errors here do not estimate a distribution-free error probability. Timing is measured in fixture steps; cost differences and shared-error behavior in real models remain unestablished.

Four neural model arms are NOT_RUN. The common-misjudgment fixture writes a wrong goal value; it is not actual ensemble inference. The function intervention is not a neural activation intervention.

Controller CPU and operation wall times were measured. Child CPU, physical energy and full provider costs remain unknown. Failed and cancelled counterexamples remain in the native unit logs; no uncertain effect is automatically retried.

Native execution used the source hashes in SOURCE_BINDING.json. Final locked Ruff 0.15.13 formatting preserved every Python AST. As required by AGENTS.md, tests were not rerun after formatting; exact published-head CI is a separate observation. The upstream just fmt invocation succeeded but selects no experiments paths, so the explicit locked Ruff check is also retained.

The validation tree is an exported package plus exact upstream formatting infrastructure, not the entire repository. No full Rust workspace or production Agentd qualification is claimed.

Archive SHA256: `b14e180f94f1c0da64288f4113508ae85fa863532c3eb21dec75a2c7cb0a3766`.
