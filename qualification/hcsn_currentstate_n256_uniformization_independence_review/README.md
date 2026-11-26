# N256 provider implementation-independence review

Status: **HOLD / all_closed=false**.

This separately frozen source-only review binds the exact N256 candidate, existing independent oracle, and standard-library uniformization provider. It verifies by AST that the candidate and oracle remain separate SciPy `expm_multiply` lineages while the provider imports only the Python standard library and implements a modal-Poisson recurrence without importing or calling either older lineage.

This establishes implementation-level separation for the three exact sources. It does not establish organizational, author, reviewer, machine, or external-custody independence. `external_reviewer_independence_certified` therefore remains false, and the provider is not admitted.

The review parses source only. It performs zero N256 dynamics, sparse actions, Poisson recurrences, candidate/oracle/provider executions, model calls, optimizer calls, or training. No idempotency key exists.

This does not close actual tail/rounding certificates, every roster operator, external reviewer independence, provider admission, the 18,225,028-record stream, three-way comparison, saved-state pairs, resources, migration, fullnetwork/equal-budget benefit, asynchronous cost, C2 full replay, HPCA external custody, or production adoption. Historical RED/UNKNOWN and #6247 finite-domain failure remain unchanged.
