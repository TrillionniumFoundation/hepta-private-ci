# Read the actual E4 Circuit receipts

This standalone reader is separate from the frozen inference source. It checks the protocol, every graph/contract, original and additional study bindings, node requests/outputs/verifiers, and each call's pool intent/request/result/raw output. It recomputes tokens from the retained model output.

Search, original arms/removals and added controls are counted once. It reports first/last success, recovery, regression, effective removals, ineffective removals and identity-replacement no-ops. Full accounting requires the planned 162 graphs and 306 complete call/verifier/pool records; any missing or failed evidence keeps complete totals unknown.

Pool, fit, route validation, provider, verifier, graph and worker wall times are nested scopes and must not be added together. Complete token/call accounting still does not establish complete monetary, energy or system cost. Old exposed tasks do not become independent samples.

The empty-run and missing-PLAN tests are explicitly synthetic readout fixtures. Both retain INCOMPLETE status and null complete totals. The JSONL contains derived copies of their retained receipts. Required formatting preserved the final tested reader's AST; no model inference was performed for these checks.
