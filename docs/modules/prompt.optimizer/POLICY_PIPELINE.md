# Prompt optimizer policy implementation

`codex_hepta_prompt_optimizer::canonical` is the single active policy pipeline.
The retired `policy*.rs` files were not reachable from the Rust crate root and
are intentionally removed; Git history retains their provenance. Do not count
those files or their historical tests as current implementation evidence.

The compatibility calculators live under `codex_hepta_prompt_optimizer::compat`.
Temporary root re-exports preserve existing source callers and receipt digests.
They neither authenticate causal evidence nor establish production composition.

The active operations are `enumerate_factors_v1`, `price_factors_v1`,
`select_portfolio_v1`, and `exercise_v1`. The technical guide and implementation
map must describe these actual symbols, their consumer callsites and executable
tests. File existence alone is not compilation, test execution or acceptance.

## Qualification boundary

Keep `productionImplementation`, `productExecutionProved`, independent acceptance,
activation and release false until the applicable executable checks succeed.
No receipt produced by this optimizer grants provider or effect authority.
