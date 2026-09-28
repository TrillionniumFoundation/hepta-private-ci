# Exact-source verification receipt

Candidate lane: `work/authbus-ownership-transactions-20260928`.
This file defines acceptance, not a declaration that an unobserved CI run passed.
The ownership model and transaction dispositions are specified in
[OWNERSHIP_AND_FAILURES.md](OWNERSHIP_AND_FAILURES.md).

## Read-only execution

The candidate's checked-in sources are the test inputs. The verification workflow
has read-only repository permissions, does not run migration/patch scripts and
does not format source in place. Formatting uses `rustfmt --check`. Dependency
resolution uses the checked-in lockfile with `--locked`. Each suite retains its
own log even when another suite fails. The final gate checks both the working
tree and index and rejects untracked files.

`verification-manifest.json` is produced outside the checkout and uploaded with
`authbus-execution-<source-sha>`. It contains the observed commit and tree hashes,
recorded input identity, run/attempt, runner platform, each required step's raw
outcome and conclusion, and SHA-256/byte length for each required evidence file.
The upload itself is not an acceptance signal. A skipped, cancelled, failed or
unrecorded step, missing log, or identity mismatch sets `candidate_verified` to
false. `continue-on-error` cannot turn a raw failed outcome into success.

The receipt builder has standalone regression tests. It hashes actual retained
bytes; it does not synthesize test counts, performance results or production
measurements. An absent receipt after cancellation/timeout is missing evidence,
not success. GitHub's terminal run/job conclusions remain authoritative; the
receipt also cannot certify a separate Linux job or a later commit.

## Constraint-to-test additions

These rows extend the matrix in OWNERSHIP_AND_FAILURES.md. Test existence alone
is not a pass receipt; use the exact run SHA and suite outcomes above.

| Constraint | Source boundary | Regression |
|---|---|---|
| A live worker/pool keeps the actual cross-process owner lock | `authority_store.rs`, `owner_fence.rs` | `live_worker_retains_owner_after_original_host_handle_is_dropped`, `cloned_pool_retains_owner_until_its_final_capability_is_dropped` now invoke a fresh-process lock probe |
| Shutdown yields to asynchronous connection cleanup | `host.rs::close`, `host_tests.rs` | `second_owner_is_rejected_and_release_allows_reopen`, `kill_nine_releases_the_process_owner_fence` |
| Trigger fault injection changes the intended schema object | `authority_schema_tests.rs` | `missing_and_replaced_authority_triggers_fail_closed_on_reopen` uses one transaction and asserts the exact trigger is absent before replacement |
| Revocation tests cannot mutate sealed issuer material | Evidence authority-backed test fixture | `expiry_and_current_revocation_are_terminal_and_never_acknowledged` |
| Legitimate persisted Bao uncertainty/terminal states can reopen unchanged | `lease_lifecycle.rs::validate_lease_metadata` | `every_durable_lifecycle_state_round_trips_without_becoming_active` |
| Newly issued leases still must be Active | `lease_lifecycle.rs::validate_new_lease` | `nonactive_new_issue_observations_are_rejected_without_partial_publication` |
| Delayed renewal cannot revive a terminal or revocation-unknown lease | `reconcile`, `refresh_lease_uncertainty` | `stale_renewal_cannot_resurrect_terminal_lease`, `reconciling_one_operation_does_not_clear_another_unknown_operation` |
| Relaxing the issue-only rule does not relax retained identity/integrity checks | `validate_state`, metadata validation | `malformed_retained_metadata_and_missing_operation_target_fail_closed` |
| An archive, skipped suite or mismatched SHA cannot imply success | receipt builder | `scripts/test_authbus_verification_evidence.py` |

## Interpretation boundaries

Owner histograms measure entry through publication, including queue time.
Evidence ACK latency measures enqueue-to-ACK, including retries, not provider RTT.
The `owner_latency` runner workload measures actual enrollment/reopen behavior and
records executable peak RSS separately from compilation. None of these outputs
is a production SLA or an independent target-host crash/power-loss drill.

Bao's metadata lease registry and AuthBus's authority checkpoint are different
state owners. The lifecycle fixes do not declare the complete Bao filesystem
backend production-qualified. Production activation, external exporter wiring,
alert thresholds, target-platform durability and independent acceptance remain
separate review gates. No script in this lane enables deployment.
