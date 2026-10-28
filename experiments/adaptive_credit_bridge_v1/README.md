# Authenticated local research credit bridge

This integration uses the original trained v2 SNN owner and the original signed
learning ledger implementation. A durable Python adapter requires a successful
authenticated terminal closure before it sends the owner's existing `Settle`
command. The next episode uses the resulting native resource account and price.
It is an integration qualification, separate from the frozen v2 efficacy study.

## Actual production code exercised

The isolated Rust executable builds unchanged copies of `hepta-types`,
`hepta-intuition`, `hepta-cognitive-types`, `hepta-memory-retrieval`, and
`hepta-learning-ledger`. It source-composes the complete original
`hepta-intelligence/src/outcome_credit_v2.rs`, without changing its bytes or
enabling the legacy qualification-write feature. Calls use actual
`activate_learning_trust`, `DurableLedger`, `LedgerWitnessStore`, `LedgerWriter`,
`append_decision`, and `append_outcome_credit_v2`.

The signed Decision is admission to execute the trained readout, with explicit
`abstain` and `execute-trained-readout` candidates. It precedes all observations.
Individual hard SNN actions remain the original owner's actual decisions and are
bound into the terminal owner checkpoint and observed Outcome. This distinction
avoids claiming that a task-admission receipt is itself the neural stopping action.

The original owner executable remains byte-identical. Its API does not acquire a
new signature-verification capability. The new adapter owns the signed admission
gate; using the owner directly outside the adapter bypasses this research gate.
Neither executable grants production execution authority.

## State and ordering

1. Open the original owner with the trained model, context, initial native account,
   and the next exact account sequence.
2. Append an authenticated run-admission Decision. The adapter binds case, organ,
   model, checkpoint, owner binary, context, budget and initial account.
3. Submit only current observations. Execute the actual eight-cell hard SNN and
   stop when the original owner terminates. Future evidence remains driver-only.
4. Persist the pending terminal checkpoint, actual work, observed utility and
   complete closure request. No resource credit has been issued yet.
5. Append the authenticated Outcome and CreditBatch. The complete original
   adapter preserves its partial-Outcome-commit semantics when credit is refused.
6. Accept the successful closure only if its complete identity and support digest
   match the current pending task. Then call original `Native Settle`.
7. Verify the native resource record's exact payload hash and the independently
   persisted `SETTLEMENT.json` outcome binding before acknowledging settlement in
   the durable adapter gate. Only this state admits the next episode.

Every gate event has an append-only hash chain and is synchronized to disk. Every
RPC response, including failures and retries, is saved in its natural per-process
directory with send/receive monotonic timestamps. The independent audit verifies
that signed acknowledgements actually preceded the corresponding owner actions.

## Meaning of Organ Credit and resource feedback

The real signed `CreditBatchV2` conserves the observed task reward in Q32 and
assigns it to the research organ. The original research resource account maps the
accepted reward into its refill and shadow-price rule:

`work = actual owner observation ticks + actual SNN spikes / 8`

`balance_next = min(32, balance_before - work + B + 0.5 * reward)`

`price_next = clip(price_before + 0.005 * (work - B - 0.5 * reward), 0, 0.08)`

The next owner episode builds its stopping boundary using
`base_observation_cost + 2 * price_next`. Price is fixed during each episode.
The learned surrogate parameter lambda remains distinct from this resource price;
mu, sigma and lambda are the exact formal checkpoint's training parameters.
The hard SNN runtime uses its trained weights and thresholds, as in the frozen
comparison. Budget units are declared observation/spike units, not joules.

## Scope of the signing fixtures

Each run creates distinct random research root, generator, observer and allocator
keys. All are controlled by the same researcher. The real verifier checks its
normal signatures, principal roles, scopes, authority epochs, validity windows,
causal binding and controller-separation fields. No production credentials are
read, and this fixture does not establish organizational independence or install
a production trust root. Logical fixture times are part of the synthetic trust
domain. Keys are included only in the explicitly identified research replay
artifact and never represent a production account.

## Qualification and failure evidence

The committed `PROTOCOL.json` fixes one 16-episode seed-601 meta-trained sequence.
It does not select tasks based on the adapter's output and does not make a new
statistical efficacy claim. The sequence exercises malformed observer signatures,
stale ledger head, partial Outcome commit followed by invalid allocator signature,
expired evidence, signed commit before adapter acknowledgement, and native
settlement before adapter acknowledgement. These use real append/recovery paths.

Additional negative cases use real successful receipts from another episode,
altered terminal identity, altered native record digest, and altered durable
outcome identity. They must leave both gate and owner bytes unchanged. The audit
also rejects torn and tampered gate files. Acknowledgement-loss injection closes
and starts real fresh processes; it does not emulate a physical power failure.

The audit independently verifies Ed25519 proofs with Python `cryptography`,
reconstructs the canonical root trust distribution and typed signed payloads,
matches every ledger authentication digest, checks all 48 signed facts, replays
every observed SNN prefix, reconstructs balances and prices, and starts a fresh
original-owner process for each episode. Exact signed and resource retries must
append no additional facts or credit, and the raw owner/ledger files must remain
byte-identical after the complete audit.

## Source freezing and execution

`provenance.freeze(destination, source_commit, v2_seal)` refuses any input whose
bytes differ from the specified Git commit. Its inventory includes the protected
v2 inputs, all five original production crate sources, the original outcome
adapter, and this integration's Python/Rust/protocol sources. The new source seal
does not alter the v2 seal or its statistical comparison.

`requirements.txt` pins NumPy, SciPy and cryptography. The new seal records and
checks the Python executable identity and installed versions. Source inputs must
be ordinary files inside the repository; symbolic file or parent-directory paths
are rejected. Verification checks both their SHA-256 identities and the matching
blobs in the sealed Git commit.

A portable replay export must call
`provenance.materialize_git_proof(export_root, bridge_seal)` and retain its result.
This supplies the exact commit, required path trees and every sealed input blob.
It is an explicitly partial Git object store supporting the unchanged source
verification, not a complete repository or history. Source files alone are not a
sufficient portable export. Replay still requires the pinned Python environment
and the exact original owner and signed-bridge executables.

Before freezing, development builds/runs are explicitly labelled
`development_only`. A formal build requires `--bridge-seal`; a formal run refuses
a development binary or a missing bridge source seal. Typical commands, from the
repository root, are:

```bash
python3 -m experiments.adaptive_credit_bridge_v1.build \
  --destination <new-build-root> --compiler <rust-toolchain-bin> \
  --source-seal <protected-v2-seal> --bridge-seal <committed-bridge-seal> \
  --cache <existing-cargo-cache>

python3 -m experiments.adaptive_credit_bridge_v1.run \
  --destination <new-run-root> --preserved <exact-preserved-v2-batch-root> \
  --bridge-build <new-build-root> --source-seal <protected-v2-seal> \
  --bridge-seal <committed-bridge-seal>

python3 -m experiments.adaptive_credit_bridge_v1.audit \
  --run <new-run-root> --destination <new-audit-root> \
  --source-seal <protected-v2-seal> --bridge-seal <committed-bridge-seal>
```

Each stage starts accounting before input validation and materialization. A
failed build/run retains its own `FAILED.json`, raw diagnostics and partial
evidence. Enclosing stage CPU includes child processes; per-RPC/process timing is
diagnostic and must not be added again. Signing, recovery, Python reconstruction,
durable receipt writes and fault checks are measured as engineering costs outside
the organ's declared resource budget. Build acquisition verifies exact frozen
package checksums, and the repository Cargo lock remains unchanged.
