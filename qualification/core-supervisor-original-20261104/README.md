# Original Core and Supervisor followups

The exact source repairs are already committed at `a3bf4c98b619244f0c81ab900aa086495b31d62e`. This isolated workflow executes the two originally failing Core cases and the full original one-case restart recovery integration binary, followed by original scoped `just fix`. Windows and Linux use the committed Rust 1.96 toolchain, nextest 0.9.151 and the original repository launcher.

The complete compiled inventory is retained. Only the two named Core cases are selected for this qualification; all other Core cases are explicitly recorded as outside this scope. The Supervisor binary is not filtered. Fresh JUnit must cover the intended case set exactly once with no failure, skip or retry, and each compiled binary must be unchanged through execution. Eleven evidence-reader controls do not count as product cases.

All tracked input bytes, locks, original assertions and time limits remain intact. The repository formatter and scoped Clippy must leave the source unchanged. This is a narrow native gate, not full Core, full Supervisor, deployment or external-model acceptance. Initial status is pending; no local native execution is claimed.
