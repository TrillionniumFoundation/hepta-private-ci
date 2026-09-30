# `learning.operator` operations runbook

State and identity semantics are defined in
[ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).
`coordinate_learning_operator_shadow_v1` is the implemented coordination
contract; real owner-port adapters and a default runtime caller remain work.
**Production activation remains false.**

## Candidate preparation

1. Freeze training data from the durable owner and retain the exact source-set,
   ledger head, row commitment, authority epoch, stop epoch and expiry.
2. Construct `TrainingProfileV1` or `WorldModelProfileV1` from semantic values;
   never accept a separately supplied profile digest.
3. Issue a non-`Clone` final-use capability with `FinalUseFenceV1`, trusted
   `FinalUseWitnessV1` and `WorkControlV1`.
4. Fit only through `fit_tabular_final_use_v1` or
   `fit_world_model_final_use_v1`; both revalidate before and after fitting. Their retained monotonic fit context
   checks actual elapsed deadline and final cancellation, even if caller witness
   timestamps remain unchanged.

## Independent evaluation and shadow

Use a separately frozen future-window dataset. Evaluator and selector identities
must differ from the producer. Persist the selected candidate create-only, load
it in a fresh process with a new boot nonce, run read-only shadow observations,
and obtain a currentness/revocation receipt. A host executing the coordinator
contract always restores the exact predecessor after the test. Current fixture
ports do not constitute that real owner composition.

Refresh owner witnesses at every final use. An immutable loaded predictor or
static selected token cannot detect later withdrawal, registry changes, trust
rotation or emergency stop. Selected predictors also reject times outside their
selection window; the evaluated ranker revalidates its current host providers.

## Trust rotation, revocation and emergency stop

Rotation creates a new immutable trust snapshot; it never rewrites evidence.
At or after revocation, final-use or read-only revalidation fails and the
candidate is rolled back. A stop-epoch change, cancellation, clock regression,
deadline expiry, authority-epoch movement, ledger-head movement or registry
movement closes the candidate. Do not fall back while retaining learned-policy
claims.

## Rollback

Rollback must bind the failed artifact and selection, restore the exact
predecessor artifact and generation, preserve owner/authority/stop epochs and
emit a nonzero rollback digest. Failure to reopen the exact predecessor is a
terminal stop condition. `PersistenceOutcomeUnknown` and `RollbackFailed`
retain the run, candidate, selection and any reported storage binding for owner
reconciliation. Do not blindly retry or clean an unrelated reported object.
Verified persistence is cleaned up even after work expiry. A replacement
candidate is never synthesized during rollback.

## Qualification operations

The authoritative repository workflow is
`.github/workflows/learning-operator-authoritative.yml`. It has read-only
contents permission and no path filters. Its stable final check is
`Learning operator authoritative qualification / qualification-result`.

The job runs exact-source contract, all-target build, module and Agentd state
space tests, payload mutation/replay rejection, operator coverage, executed
source mutation, 1K–16K/100K–1M performance matrices, strict Clippy/format and
a deterministic synthetic merge. The generated manifest binds source, runner,
toolchain, lockfile, test set, workflow run and every evidence log.

## Claim boundary

Repository success does not issue independent scientific acceptance,
target-host benchmark acceptance, future-window efficacy, canary acceptance,
promotion, activation or release. Those values remain false in the receipt;
activation remains false.
