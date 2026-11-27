# Original evaluator read-only recovery

This scoped P0 change adds an evaluation recovery route that receives no holdout provider or signing capability. It reads only an existing execution, retains the original plan, evaluator, current trust, holdout fence and consumption checks, and keeps Missing/Pending unresolved. The Cell adapter also checks the original frozen Cell journals before contacting the execution owner. It grants no learning, selection, publication or product-use authority.

On the exact working-source inputs retained in `NATIVE_SOURCE_INPUTS.json`, the original workspace's `codex-hepta-intelligence-eval` package passed 143/143 native tests, including the new Missing/Pending cases and abrupt-process recovery through the new read-only route. The same 180 recorded component source/manifest/lock files remained unchanged during execution and the subsequent scoped `just fix`. The earlier 141-case run is a separate pre-extension window; its count is not added to 143. Six source-closure mutation tests passed.

The full caller scan found an inherited unresolved post-claim `source_state` receiver. Its original bytes failed the scoped boundary check; an explicit `Arc<AgentdState>` binding passes without changing runtime behavior. A complete caller scan on the final integrated candidate is still required.

Initial missing-nextest/offline-dependency attempts are retained. Official, digest-verified tools and original locked dependencies subsequently enabled the actual workspace run. No dependencies or lockfiles were changed.

Agentd's authored Cell-level native cases, final common-candidate CI, the real production StageOwnerPorts implementation, A→learning→independent B→C and whole daemon/Root cold recovery remain unqualified. All cohorts and signing keys in these mechanism tests are synthetic; zero new independent confirmation tasks or training fits were added. Full P0 remains NOT_ESTABLISHED. Root performs final common-source formatting and qualification; tests were not repeated after scoped fix.
