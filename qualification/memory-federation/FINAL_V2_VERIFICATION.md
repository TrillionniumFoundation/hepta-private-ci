# memory.federation V2 final verification

- branch: `fix/memory-federation-v2-closure-20260920`
- base main: `331b81d385a88837e252bd80fda8b8ac35ea4191`
- candidate implementation head: `1b470b31b266e58bcde1f924f41fd09050225d6d`
- candidate implementation tree: `872a2bd3f9b2f913958373f8105c39e8ecd701bc`
- status: `pending_exact_current_head_execution`
- claim boundary: source/product-composition candidate only; no activation, release, or product-execution proof is asserted here.

## Required checks

The candidate must pass the repository workflow `.github/workflows/memory-federation-v2-final-verify.yml` plus the normal exact-head and deterministic merge-candidate gates before `productExecutionProved` can change.

Focused checks cover formatting, the canonical federation contract, product adapter and legacy regression, extension federation attachment, Agentd runtime composition, source-composition assertions, strict Clippy, and a clean diff check.

## Historical note

The earlier `fix/memory-federation-v2-hardening-final` receipt was a failing development receipt, not acceptance evidence. Its actionable federation-local failures (authority-horizon fixture inconsistency, missing extension test import, and strict Clippy enum-size lint) are repaired in this forward-port before new qualification is evaluated.

The frozen candidate also binds `observed_frontier` to the exact-scope owner memory frontier acquired from the same SQLite snapshot as candidate retrieval; empty scopes may truthfully use frontier zero. Response integrity is prefix-order-sensitive because `maximum_results` selects a response prefix, and `Partial + []` remains partial rather than being relabeled as valid-empty. Product model-input registration and revalidation are V2-only source APIs; the legacy AvailableFederated variant cannot silently satisfy the canonical product attachment path.
