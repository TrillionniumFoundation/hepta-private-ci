# Trained native owner and causal resource credit

This composition executes the repository's original `AgentdNeuronOwner`, `NeuronRuntime`, journal, witness, sparse transition, and credit finalizer. The source-composed `neuron_runtime.rs`, `causal_v2.rs`, and measurement allocator remain byte-identical to their repository inputs. The SNN inference port, stopping readout, and research resource account live in this experiment directory; production permission and ledger admission are not expanded.

## Causal execution

`Open` accepts the trained profile, model/checkpoint digests, observable context, policy, budget, and expected account sequence. `Observe` accepts only the current binary observation, elapsed time, event identity, and evidence digest. The driver holds the complete exogenous stream and hidden truth for evaluation. Neither is passed to the inference interface.

Each native owner tick calls eight hard bipolar IF cells. A cell accumulates the six registered features, emits at most one signed spike, subtracts the corresponding threshold, and updates its spike trace. The readout is the weighted trace plus bias. Inference never evaluates the first-passage surrogate or its cancellation parameter. The deployed JSON is regenerated from the actual training checkpoint and checked before admission.

The readout maps its logit to a belief and uses a finite-horizon Bernoulli Bellman table. The observed reliability, base cost, remaining horizon, and episode-frozen resource price are identical public information for the SNN and raw-belief comparators. Raw comparators execute zero SNN cells and spikes. The table solves the declared discretized problem with conservative quoted cost `base_cost + 2 * price`; this is not a claim that an uncalibrated learned logit equals the true posterior, or that the quoted-cost policy solves a different objective charging a state-dependent number of future spikes. The numerical-domain certificate is not task-success calibration.

A terminal recommendation actually terminates execution: the driver purchases no later observation, and the owner rejects further nonduplicate observations. Native fallback also terminates and scores the registered abstention reward. The first observation is charged in every policy.

## Resource and native credit

Actual resource work is one purchased observation/owner tick plus the observed spike count divided by eight. It is a declared budget unit, not an estimate of Joules. Raw baselines spend one unit per actual tick. A conservative two-unit quote prevents a tick from overdrawing the account. If another quote cannot be reserved, the current decision becomes a budget abstention before another observation is purchased.

The account debits actual work and settles only after an independently evaluated terminal outcome:

```text
price_next   = clip(price + eta * (work - budget - kappa * reward), 0, pmax)
balance_next = min(cap, balance_before - work + budget + kappa * reward)
```

Overflow at the balance cap is recorded explicitly. `off`, `frozen`, and `live` all maintain the same account rules; only the applied price differs. Price remains fixed inside a task and changes only between tasks. The backward surrogate's `lambda` is neither this resource price nor a physical runtime killing rate.

Each settlement actually calls original `finalize_credit_batch` with a conserved organ allocation. Its support binds the observed outcome and native owner checkpoint. Native credit identity and conservation are persisted beside the resource-account transition. The allocator principal fields are structural research metadata: no cryptographic signature admission or production `LedgerWriter` append is claimed.

The account is append-only, hash-chained, and rejects repeated case identities. Expected sequence checks prevent lost account history from silently granting a fresh balance. Event retries perform no new tick, spike work, or debit. Settlement retries validate the original allocation but append no second credit. A committed settlement with a stale reservation is reconciled without adding credit again.

## Evidence, build identity, and replay

`build.py` starts wall and parent/child CPU accounting before input validation, source copying, vendor checksum verification, dependency preparation, or compilation. It verifies every borrowed vendor file and the repository lock, downloads nothing, and preserves failed build receipts. The receipt identifies the actual copied native source bytes, generated workspace recipe, compiler, lock, and executable. Reproducible mode disables incremental compilation and remaps paths.

Scientific builds require a committed source seal at build time. Scientific execution and audit independently require the same seal, exact native input closure, successful build receipt, and executable hash. A development executable cannot be relabeled as a sealed scientific build. `serde_json` uses `float_roundtrip` so persisted floating-point spiking state reconstructs exactly; native event and checkpoint comparisons remain strict.

`run_organ` keeps natural per-case native journals, witnesses, event ledgers, identities, settlements, complete RPC records, process costs, and exact checkpoint/profile bytes. It checks every causal prefix against independent Python scalar SNN and Bellman calculations, retries the first observation and terminal settlement, and cold-restores an unfinished task when possible.

`audit_organ` requires an independently generated expected plan, reconstructs every observation, stop, outcome, resource transition, and counter, then opens every historical task in a fresh native process. It verifies complete native recovery and idempotent settlement and checks that the replay changed no raw evidence bytes. Its computation and validation calls are charged separately. Original ack timing in a retry is never charged as a second tick. Peak counters aggregate by maximum; work and elapsed operation counters aggregate by sum. Preparation, solver, hashing, reconstruction, and bookkeeping are included in parent CPU/wall costs; native process CPU and per-RPC measurements are retained separately.

For replay at a new filesystem root, issue a new explicit local research permit for that root and retain the original permit and a relocation receipt. Checkpoint, model, native journals, witness, events, and settlement evidence remain unchanged. The audit replaces only absolute transport paths to the same local profile and certificate bytes.

## Interfaces and development checks

```python
run_organ(binary, destination, organ, model_path, checkpoint_path, policy, episodes,
          source_seal=seal, build_receipt=receipt)
audit_organ(binary, root, source_seal=seal, expected_plan=plan, output=audit_path)
```

An episode is `{case, context: [reliability, base_cost, deadline], budget, observations, truth, stream_id}`. The plan is `{organ, policy, episodes}`. `policy` chooses `snn`, `raw_belief_dp`, or `raw_belief_myopic`, and `off`, `frozen`, or `live`. Complete stream/truth fields stay in driver/audit evidence only.

Run the Python contract tests with `python3 -m unittest experiments.adaptive_neuron_v2.owner.test_owner`. `qualify.py` consumes a marked task-trained development checkpoint and checks all nine readout/price combinations, full cold replay, measured feedback changing an actual stopping trajectory, budget overflow, checkpoint alteration, roster disagreement, conflicting retries, reservation recovery, and lost-account rejection. These fixtures do not consume scientific seeds or support efficacy claims. All development attempts, including failed fixtures, are retained.
