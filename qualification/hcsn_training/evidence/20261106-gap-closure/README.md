# HCSN gap-closure source and evidence

Implementation entry point: [PR #5001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5001), nine draft stages below 500 changed lines each. Current source is `44e539313e0c54badb4b9b687425dd87ecba6e67`, tree `b7ac591c98b6045521f70e97f58dc2cea8bf12bc`.

## Current candidate

The current candidate adds a 32-line owner-boundary correction after the first qualification: FinalUseAuthority construction remains inside the existing Agentd effect owner, shared privately by HTTP and HCSN. The caller allowlist and verifier are unchanged. Their exact closed-set proof is now included in the Agentd job. Current [run 42222767973](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42222767973) is in progress; no final result is claimed here yet.

## First candidate qualification

`ci-e62f132/` retains the complete dedicated qualification for exact head `e62f1329142c5752d0344b5fa64f3a9c981f4be5`, [run 42220007503](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42220007503): 56 Python tests with zero skips, 195 native tests, 119 Automation tests, three explicitly executed signed-worker fixtures, complete owner/cold/second-block evidence for all three backends, and seven selected actual Agentd tests plus Clippy. Existing helper skips and 168 filtered Agentd tests are recorded separately. The second training blocks use new real workers and owner recovery; they are not second signed TaskFlow dispatch tests.

The primary artifact excluded one nonregular negative-test FIFO. Its README distinguishes evidence-based attribution from an unavailable remote lstat. All required bridge checkpoints, handoffs, owner/SQLite state, source identities and logs are retained. Original executable bytes remain in the Actions ZIP where present; retained archives document each exclusion and its digest.

The broader repository workflow was not green. It exposed the introduced constructor-caller error corrected in the current candidate, alongside unrelated baseline failures including README readiness discovery, Windows long paths and the removed append_qualification call in an unchanged plasticity test. Original caller/readiness failure logs are retained in the first-candidate bundle.

## Physical and recovered local evidence

`ai395/` is imported with unchanged subtree `42d568588a7572d4d364a344912ed59492a84487` from evidence commit `7176667c0807ee49bd6bfc9a571b175f44a243a1`. It contains three completed real CPU acceptances, binary build/strip/deployment linkage, retained local logs and explicit accounting for RAM-only output trees lost in the execution-environment interruption. Original code was recovered byte-for-byte and preserved at `e989d51b0da0617aa20a1fccbcbcb4ad01571ff4` before formatting. Final CI outputs do not overwrite or relabel that preformat evidence.

## Scope

Actual task-loss autograd stays separate from NDU, receipts, eligibility and local plasticity. Physical-time B uses a conservative discrete CTMC and integer-time refractory cohorts with admitted budgets; it does not claim an exact continuous nonlinear PDE. Complete numerical state crosses persistence boundaries; each new training block starts detached.

Production PQ authority/deployment remains unavailable on this baseline. Engineering registration is test-only; ordinary debug/release and the uncomposed production profile are refused. Physical helper results explicitly state host_registration_exercised=false; actual Agentd tests have their separate job. No production adoption, scientific gain, energy measurement or new CUDA campaign is claimed.
