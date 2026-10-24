# Original issuer key publication and unused installation recovery

The original `DeploymentFinalUseIssuer` remains the single owner of its signing
key, policy, revocation head and sequence. Issuance, FinalUse bindings, request
locking, lease verification, expiry checks, wire protocol and ordinary runtime
opening keep their existing implementations.

## Publishing a new key

Fresh `create` and `create_protected` still refuse an existing issuer directory.
Inside the newly created private directory, key creation now follows this order:

1. Hold a private initialization lock and the opened directory descriptor.
2. Exclusively create `issuer.key.next` with the original owned mode 0600 and
   write all 32 bytes from the original random source.
3. Synchronize the complete candidate file and its parent directory.
4. Publish that same inode as `issuer.key` using `RENAME_NOREPLACE`.
5. Synchronize the directory and read back the canonical file, checking its
   original metadata, exact bytes and retained inode identity.
6. Provision the original issuer state, synchronize it and perform the original
   issuer open.

The initialization lock is coordination, not a new authority record or operation
ledger. It remains held through original state provisioning and final open.
Publication uses the held directory descriptor. It introduces no new unsafe
block; the existing locked `rustix` dependency supplies the safe filesystem
calls.

A collision cannot overwrite an existing canonical key. A failure does not
delete an uncertain candidate. An incomplete temporary seed is retained and
refused. The code does not invent the missing bytes or generate a replacement
identity over that evidence.

## Explicit Root-only continuation

```rust,ignore
DeploymentFinalUseIssuer::resume_protected_initialization(
    directory,
    signer_id,
    policies,
    clock,
    original_lease_verifier,
    original_lease_id,
    original_lease_revision,
)
```

The parameter shape matches `create_protected`, but this is an explicit
administration operation on an existing protected directory. The complete Root
ancestor checks, original clock and original lease objects still apply.
Ordinary `open` and `open_protected` do not call it after an error.

The expected state is the exact original unused genesis: the original signer
and ordered policy vector, authority epoch 1, head revision 1, no revoked grant
IDs, sequence 0 and no writer authorization. The caller must recover the
original bootstrap. A new boot's policy must not be substituted for the old
bootstrap to make it match.

| Retained material | Result |
| --- | --- |
| Complete canonical key and exact unused original state | Read and verify the same original identity and state. Do not reset or reprovision them. |
| Complete canonical key but no state | Complete only the exact original unused state through the protected store's explicit initialization method. |
| Complete canonical key and complete original state candidate | Complete only a candidate equal to that exact unused state; preserve and refuse other candidates. |
| Complete key candidate, no canonical key and no other state material | Publish the same candidate inode and continue the exact original initialization. |
| No key material and a genuinely empty directory apart from the initialization lock | Under explicit fresh administration, create the first identity using the original random source. |
| Short key, invalid metadata, conflicting canonical and candidate keys, or partial candidate | Refuse and retain the files. |
| State exists but the canonical key is missing | Refuse, even if an isolated complete key candidate exists. The state does not establish that candidate's signing identity. |
| Sequence, writer authorization, head, signer or policies differ from the unused original genesis | Refuse. Continue through the original runtime or a separately authorized administrative lifecycle instead. |

The protected store bridge uses its original publication lock and complete
record decoder; see
[ROOT_FRONTIER_INITIALIZATION.md](../hepta-contracts/ROOT_FRONTIER_INITIALIZATION.md).
It never interprets a generic read error as absence. A partial or later state
candidate is not truncated to restart genesis.

The returned pinned lease is still the original lease. This operation does not
renew it or turn an expired lease into live authority. Subsequent issuance and
live observations still pass the original lease revision, binding and expiry
checks. A successor lease requires its own original registry transition.

## Identity and recovery limits

A 32-byte Ed25519 seed has no intrinsic corruption checksum, and the original
issuer state does not embed its verification key. Shape checks can reject short,
oversized or improperly protected files; they cannot identify an arbitrary
32-byte substitution by themselves. Whenever an installation has a retained
public-key pin or signed original material, the caller must verify that same
identity through the original installation checks. This helper does not replace
those checks or claim protection against the trusted Root administrator
replacing all protected state.

There is no recovery from missing private-key bytes. The implementation retains
that evidence and fails closed. A separately authorized fresh installation is a
different action. Likewise, this issuer path must not be used to reconstruct a
lost time-dependent clock record using the current time.

## Regression and actual process-death tests

Three ordinary component tests in `deployment_issuer::initialization::tests`
exercise real filesystem operations:

| Test | Boundary |
| --- | --- |
| `key_publication_preserves_existing_identity_on_actual_noreplace_collision` | A controlled target appears after candidate preparation; the actual non-replacing rename returns `EEXIST` and preserves both files. |
| `key_publication_refuses_partial_canonical_and_partial_candidate_without_replacement` | Invalid seed lengths are refused without generating or publishing another key. |
| `key_initialization_holds_an_exclusive_actual_file_lock` | A second open cannot acquire the same initialization lock while the first owner holds it. |

Six explicit Root parent tests use the original clock, registry, protected
frontier store, issuer methods and protected `/run` fixtures:

| Test | Boundary |
| --- | --- |
| `root_issuer_resume_retains_identity_and_refuses_an_already_used_state` | Exact unused state resumes with the same public key; a real grant increments the original sequence and makes genesis resume fail. |
| `root_issuer_resume_preserves_wrong_or_incomplete_initialization_evidence` | Different policies or signer, short keys and missing keys with existing state remain errors. |
| `root_issuer_empty_installation_continues_once_without_replacing_identity` | A genuinely empty original installation receives one identity, which subsequent exact continuation retains. |
| `root_issuer_sigkill_after_complete_candidate_resumes_the_same_key` | An owned child is killed and reaped after complete key-file and directory synchronization. |
| `root_issuer_sigkill_after_key_publication_resumes_the_same_key` | An owned child is killed and reaped after key publication, before state provisioning. |
| `root_issuer_sigkill_after_state_publication_reads_the_same_genesis` | An owned child is killed and reaped after the original state publication, before initialization returns. |

The child selector `issuer_initialization_crash_child` is subprocess-only.
Each parent verifies the actual cut, checks initialization-lock exclusion while
the child is alive, kills and reaps only its owned child with signal 9, then
checks the original public identity, key inode and unused state. Private seed
bytes are not included in diagnostic assertions or serialized evidence.

The Root tests are ignored by default and require an explicit zero-retry run.
They exercise actual process death and filesystem operations, not host power
loss. The existing original issuer and FinalUse tests remain required. Source
review and conservation checks are not acceptance results; pinned builds,
Linux Root runs and the actual native entry must each retain their own outcomes.
