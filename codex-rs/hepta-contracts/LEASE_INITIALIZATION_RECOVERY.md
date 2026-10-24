# Lease registry publication and explicit Root recovery

The lease registry keeps its complete local state and an independently protected
frontier. The frontier contains the original authority epoch, store revision and
full state digest. A successful protected compare-and-set commits that exact
state; it does not contain enough information to reconstruct lost lease times,
revocations or retired lease IDs.

## Publication order

`AuthorityLeaseRegistry::persist_or_fence` retains the original state mutex and
exclusive local store lock throughout this sequence:

1. Encode the complete next `Stored/State` in the original format and write
   `authority-leases.next`.
2. Synchronize the candidate file. For a registry with an external frontier,
   also synchronize the local parent directory so the candidate name is durable
   before its digest can be committed independently.
3. Perform the original protected frontier compare-and-set against the original
   expected full frontier.
4. Rename the prepared file to `authority-leases.json` and synchronize the parent
   directory.
5. Publish the same next state to the original live owner.

Any error fences the live owner. Dropping the private, non-cloneable prepared
publication retains uncertain candidate evidence. It does not delete a file or
roll back a protected frontier. No record format, state hash, lease ID, issued
time, expiry, revision allocation or revocation rule changes.

The additional parent-directory synchronization before protected CAS is required
for a named candidate to survive a storage interruption. It is not a relaxation
of the original clock or client deadlines.

## Two explicit Root administration methods

Both methods require an actual Root-owned protected directory and its complete
protected ancestor chain. They take the original concrete `HostAuthorityClock`
and `HostAuthorityFrontierStore<AuthorityLeaseFrontier>`, acquire the original
exclusive local lock, and retain the actual protected frontier's publication
lock through validation, completion and full readback. They check the original
clock before and after the operation. An unavailable clock remains an error,
including when a publication has already become visible.

Neither method performs frontier CAS, issues a lease, samples a new lease issue
time or creates a new administrative epoch. Callers must still complete their
original installation, binding, identity and lifecycle checks.

### Initial installation

```rust,ignore
AuthorityLeaseRegistry::resume_initialization_with_trust(
    directory,
    owner_id,
    &AuthorityLeaseInitialization {
        lease_id,
        binding,
        lifetime_ms,
    },
    clock,
    frontier_store,
)
```

The administrator input only restricts which original genesis is admissible.
It is not a verified token and cannot authorize a different state. The method
accepts only epoch 1's original empty revision 1 or its exact first lease at
store revision 2. It rejects extra leases, revocations, retired IDs, later
epochs and later store revisions.

The first lease must have its original ID, binding and lifetime. Its complete
retained issued time and expiry are used unchanged. After completion, callers
read the original lease with `read_lease`; they must not replace it with a lease
constructed from a fresh clock sample.

Only this genesis method can complete an earliest lock-only interruption. The
independently protected full frontier must exactly equal the deterministic
original empty state. It cannot reconstruct a first lease from a lifetime or a
digest alone.

### An already committed later state

```rust,ignore
AuthorityLeaseRegistry::resume_prepared_state_with_trust(
    directory,
    owner_id,
    clock,
    frontier_store,
)
```

This method accepts no caller state or initialization fields. A valid older
canonical state may be completed only from a complete, originally valid
candidate whose full frontier exactly equals the actual protected frontier.
It preserves all issued and expiry times, revocations, retired IDs and other
original fields. The canonical state must be strictly behind the protected
store revision and must not have a later authority epoch.

An absent canonical store is always refused by this method. It cannot infer a
later state from the frontier or synthesize an earlier state to make recovery
possible.

## Completion decisions

| Observed original files and frontier | Result |
| --- | --- |
| Canonical state exactly matches the actual protected full frontier | Synchronize and fully read it back; leave any uncommitted `.next` untouched. |
| Canonical state is admissibly older and complete `.next` exactly matches the actual committed frontier | Synchronize the candidate and its name, perform the original rename and directory synchronization, and fully read back the same committed state. |
| Canonical state is current but `.next` describes a later uncommitted state | Retain the current state and the uncommitted candidate; never promote the candidate. |
| Candidate is absent, malformed, has different metadata/owner/format, or hashes to a different state | Refuse and preserve the remaining evidence. |
| Canonical state has the same revision but a different digest, or is ahead | Refuse; no rollback or replacement is authorized. |
| Canonical state is absent | Refuse, except the initial-installation method's exact original empty-state case. |
| Another live original owner holds the local store lock | Refuse with the original lock exclusion. |

Ordinary `Store::open`, `open_state_dir_with_trust` and the other existing open
methods do not call these recovery methods. Their original anti-rollback
behavior remains in place. A native cold-recovery caller must explicitly select
the bounded Root administration operation after its own required checks.

## Regression and process-death coverage

The source adds nine explicit Root parent tests in
`authority_lease::initialization_tests`. They use protected `/run` directories,
the original clock and protected frontier store, actual registry mutations and
the original local locks. They are ignored by default and require an explicit
Root run with zero retries.

| Required parent test | Boundary checked |
| --- | --- |
| `root_prepare_failure_before_frontier_cas_does_not_commit_the_initial_lease` | A failure before CAS leaves the protected and canonical state unchanged and fences the live owner. |
| `root_lost_actual_cas_result_resumes_the_same_prepared_initial_lease` | A lost result after the real CAS requires exact completion and preserves the original lease times. |
| `root_sigkill_before_original_frontier_cas_never_promotes_the_candidate` | An owned child is killed and reaped before CAS; recovery keeps the old state and leaves the uncommitted candidate. |
| `root_sigkill_after_original_frontier_cas_retains_and_resumes_exact_candidate` | An owned child is killed and reaped after real CAS; ordinary open refuses until explicit exact completion. |
| `root_sigkill_after_original_rename_resumes_without_a_second_cas` | An owned child is killed and reaped after the original rename; completion synchronizes and reads back the same canonical state. |
| `root_initialization_resume_never_repairs_a_different_or_missing_committed_state` | Genesis rejects wrong bindings, different or damaged candidates, missing evidence and later owner state. |
| `root_lock_only_initialization_completes_only_the_original_empty_state` | Only the exact independently retained empty frontier permits earliest genesis completion. |
| `root_prepared_resume_preserves_later_revocation_without_reissuing` | Later committed revocations and original lease times survive exact completion and replay. |
| `root_prepared_resume_rejects_different_missing_or_corrupt_committed_bytes` | Later-state recovery rejects candidate corruption and missing or conflicting canonical evidence. |

The child selector `initialization_crash_child` is subprocess-only. Its parent
owns, kills and reaps that exact child. Every process-death parent checks that
the original local lock excludes recovery while the child is alive. The
after-rename cut is a one-shot thread-local callback compiled only into libtests
and invoked immediately after the actual original rename.

The existing ordinary test
`external_frontier_ahead_after_local_commit_failure_fences_reopen` retains its
protected revision-2, fenced-owner and ordinary anti-rollback expectations. Its
controlled failure now occurs after the real frontier CAS at canonical rename:
pre-creating a broken `.next` would correctly fail during preparation before
CAS and would no longer exercise that original failure window. The test also
checks the retained candidate's full digest against the committed frontier.

These tests exercise real process death and filesystem operations. They do not
constitute host power-loss qualification. Source review and local conservation
checks are not test execution results; the integration evidence must record
the actual pinned Rust build, all existing tests and the nine explicit Root
parent outcomes before this change is marked accepted.
