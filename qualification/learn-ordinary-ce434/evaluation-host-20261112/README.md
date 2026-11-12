# Original Evaluator host qualification

Two independent, exact-source local Python runs are retained here.

- `57500bbdf5bc362de17828296c831e90dcb30dae`: 88 source tests, 87 passed and one failed. The failure is the unchanged old Root inventory count (16 actual workflow parents versus 15 expected). All 16 report-parser cases passed.
- `96719b494a8d887f01a6eb23f0da8ffbeb1ed928`: all 88 source tests and all 16 report-parser cases passed. Fourteen Python files compiled. Both the clean working-tree and the committed 575-to-967 diff checks returned zero.

Each run's source identity was clean and exactly equal before and after execution. Raw logs, commands, times and original byte SHA-256 values are retained without replacing the failed run. The second source adds the exact new Root child case to its source inventory; it retains all eight prior resident Root cases and all negative controls.

This is local Python/source evidence only. No Rust, native mechanisms, full caller proof, formatting, deployed role custody, positive gain or ordinary A/B/C closed-loop result is established by these files. The three added host mechanisms and one protected Root mechanism remain native-pending.
