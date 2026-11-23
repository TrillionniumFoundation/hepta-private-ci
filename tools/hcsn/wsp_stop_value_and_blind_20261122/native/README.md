# Native action veto

The standalone Rust 2021 worker consumes one supplied finite task graph and three hard action vectors from stdin. Inputs are the law, the incumbent action, the proposed weight edit's action, and the reverse-control action. The worker implements local interval bounds, backward evaluation of the incumbent, conditional rejection of inferior action changes and a one-step greedy improvement over the incumbent. It emits eight policies with complete state-by-state actions and hard initial expected payoffs. The native guard operates after an actor forward. Checkpoint decoding, model inference, graph construction, deployment and persistent parameter rollback are outside this worker.

Build with Rust 1.95.0 and no third-party crates. From the parent directory use:

```bash
curl -fL https://raw.githubusercontent.com/TrillionniumFoundation/hepta-runtime/8114c193d2e4a8f6fea4772ed93cdba104fcfd57/qualification/weight_intervention_diagnostics_20261122/policy/advantage_veto.rs -o native/advantage_veto.rs
echo "8d9bff519b7b7f03f83133fe6fbc7b2b97b089b1ee88b17d16e437de08745a44  native/advantage_veto.rs" | sha256sum -c -
rustc --edition=2021 -Dwarnings -O native/advantage_veto.rs -o native-veto
rustc --edition=2021 -Dwarnings --test native/advantage_veto.rs -o veto-tests
./veto-tests
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python native/parity.py "$HEPTA_WSP_INPUTS" veto-replay-input fresh-veto ./native-veto native-parity.json
```

The 80 sealed worlds contain 37,333 states. The parity harness regenerated the frozen proposals from stored model weights, passed all encountered branch layouts to the worker, compared every emitted action to the Python reference and compared every value to the retained prospective record. All 298,664 actions matched. All 640 values matched exactly. Across continuation slots, 84,107 were unavailable, 21,655 had one successor and 6,237 had three. Eighty native process launches and exchanges took 0.201 seconds together; end-to-end parity took 17.85 seconds including graph construction. These timings describe this run. Individual input and output hashes are recorded in `records/native/PARITY.json`.

The whitespace-delimited research format starts with `HEPTA_DAG_V1 state_count initial_index`. Each state row contains tick, six-bit legal-action mask, payoffs for terminal actions 0/4/5, then incumbent/direct/reverse actions. For each continuation action 1/2/3 the row records a successor count and triples of probability, successor index and fee. A supported transition advances one tick. Encoded payoffs must lie in [−1,1] and fees must be finite and nonnegative. The reader rejects invalid policies, invalid transition mass, unsupported graph sizes and trailing input. The two unit tests include malformed-graph cases and a concrete two-step improvement.
