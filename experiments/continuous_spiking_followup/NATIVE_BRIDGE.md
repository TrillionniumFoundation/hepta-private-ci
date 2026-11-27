# Trained HCSN to the existing native owner

This follow-up supplies a trained tensor HCSN's outputs to the genuine research
host introduced in [PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157).
The host executes the original sparse kernel, NDU and durable owner. The neural
HCSN recurrence remains in the incremental tensor adapter. The native host is a
bounded research executable; this is not a full daemon build or a native tensor
implementation. Its owner authority remains `DENY_ALL`.

## Source and executable identity

| Item | Pin |
| --- | --- |
| Original native source base | `5898cd8b0f724c3152b6cc52856721f72e5e08be` |
| Existing research wrapper | `7bec42aa4f79432f4a724d5295c67f9d69ee5a8d` |
| Native executable SHA-256 | `1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5` |
| Source-manifest SHA-256 | `6addea031fa9ba2ca403137d8d10da6088c255474c681b106d9a2706c645dd09` |
| Unmodified upstream Python adapter SHA-256 | `2a7be4914211a5166fc8ef7fbbf6a2de8632b2e7651c7175d6e3888ddbb1ec0c` |

`NATIVE_REFERENCE.json` lists all 174 original source hashes. `native_reference.py`
is an exact copy of the existing adapter, checked before loading. The new client
checks the executable hash, runtime source commit, source-manifest digest and
owner authority before accepting a profile. This work reused the existing
executable read-only and did not rebuild it or alter native guards.

`results/preflight/native_host/UPSTREAM_BUILD_RECEIPT.json` retains the original
compiler, original and resolved dependency-lock hashes, generated build-manifest
hashes, command and historical build costs. The original build retained native
Rust source bytes, omitted test-only dependencies and additionally linked the
original NDU in its research example; it was not a full daemon build. Those
historical build measurements are provenance, not a newly measured build here.

The exact 1,306,448-byte Linux x86_64 executable is stored as 580,191 compressed
bytes in two parts, each at most 400,000 bytes. Restore from the repository root:

```sh
python -m experiments.continuous_spiking_followup.restore_native \
  experiments/continuous_spiking_followup/results/preflight/native_host \
  /tmp/hcsn-native-host/continuous_host
```

The utility verifies every part, the gzip stream, decompressed size and final
hash, then sets mode `0755`. It refuses to overwrite a different executable or
a symbolic link. Native execution remains platform dependent. A future rebuild
with a different binary requires a newly reviewed pin; the client does not
silently accept a substitute.

## Distinct signal meanings

| Field | Meaning and treatment |
| --- | --- |
| `continue_score` | Declared signed decision score; positive favors another paid read. |
| `value_model_advantage` | Genuine policy-model `continuation_value - stopping_value`; both component values retained. |
| `threshold_confidence_advantage` | Fixed/direct confidence-threshold score; both task-value fields must be null. |
| `forced_terminal` | Finite-horizon constraint. Score is exactly -1 and continuation value is null; no invented finite continuation utility. A value policy retains its genuine stopping value. |
| Natural margin | HCSN natural boundary minus voltage, averaged over the final layer. Consumer retains the raw number and transports `raw / (1 + abs(raw))`. |
| Task risk | Model-predicted error probability `1 - confidence`; not a calibrated safety certificate. |
| Activity | Mean interval first-passage event probability, bounded in [0, 1]; not an instantaneous hazard or binary spike. |

All signal semantics, policy identity and causal task context enter the evidence
digest. The profile binds the objective and a composite neural-model/policy
identity. Snapshots also retain the separate neural-model and policy hashes.
No fixed/direct threshold is relabeled as a task continuation value.

## Actual native action path and its limits

The five native encoder coordinates are `score`, `-score`, `0.5 * margin - 4`,
`risk - 1` and `activity - 1`. The original sparsity constraint permits one
positive winner at width five (`top_k = 1`). Both score coordinates cannot be
positive simultaneously; the three auxiliary coordinates remain nonpositive.
The native keep readout is `[1, -1, 0, 0, 0]`, repair has fixed score -8 and the
native STOP head is exactly zero. All temporal/threshold adaptation rates in
this transport profile are zero; the trained HCSN supplies temporal processing.

Consequently the auxiliary channels enter real native temporal state, identity
and recovery evidence, but this profile does not establish their independent
causal contribution to action utility. The native head deterministically
compiles a declared decision score. It is not a newly trained native sparse
head, and its execution cannot support a claim of learned sparse-readout
superiority. These scope limits are deliberate and must accompany results.

The original native sparse activations and NDU determine every returned action.
Q24 quantization can change a near-zero decision: a positive score smaller than
half a quantization unit can become a native tie, which selects STOP. The
consumer reports this disagreement and consumes the actual native action; it
never overwrites the result with the Python policy's expected action. A focused
test exercises this case explicitly.

## Episode and recovery API

```python
consumer = NativeEpisodeConsumer(
    binary, unique_episode_directory,
    model_sha256=model_hash, objective_sha256=objective_hash,
    policy_id="value", episode_id=episode_id, seed=seed,
    maximum_steps=horizon,
    task_binding={
        "input_sha256": input_hash, "policy_sha256": policy_hash,
        "snr": snr, "cost": cost, "horizon": horizon,
    },
)
receipt = consumer.tick(
    decision=decision, natural_margin=raw_margin,
    event_activity=interval_mass, episode_id=episode_id, step=cursor,
)
restored_stream, recovery = consumer.cold_resume(stream, cursor, episode_id)
complete = consumer.finish()
```

Each episode has a unique durable directory. Inputs are immutable prepared
experimental arrays, bound by SHA-256 together with SNR, read cost, horizon,
policy and model. Task-level paid reads mean actual iterator reads and model
advances; the observations already reside in RAM. These measurements do not
claim sensor or network I/O savings.

Recovery serializes the actual neural stream state through its public API,
stores a task cursor and complete native frontier in `TASK.json`, closes and
waits for the exact old native PID, starts a new native process and resumes its
original journal. It reloads a fresh neural adapter, checks the neural files and
all model/task/native bindings, and returns the persisted cursor for the caller
to reconstruct its input iterator. Snapshot schema and elapsed-time dtype are
owned by the streaming API, not duplicated here. The Python process itself is
not restarted; the receipt explicitly records this distinction.

After native STOP, the consumer submits a fresh event and requires actual
native rejection with an unchanged status. The outer task also guards its
source against a subsequent read. Repeated valid-event handling, wrong-frontier
rejection and malformed observation rejection are tested against the real host.

## Evidence and cost accounting

Every successful tick retains the full original receipt, typed signal packet,
raw margin, bound evidence digest and any disagreement. Recovery records bind
the neural payload and manifest, task cursor, native frontier and both PIDs.
`finish()` waits for the native child and retains exact-PID `wait4` CPU usage,
maximum RSS, native physical RPC time, transfer bytes, kernel/NDU calls, journal
replay and validation work, process exit status and parent elapsed time. It
archives every original owner and task file losslessly and returns their hashes.

Parent lifetime/episode/model timings overlap and must not be added together.
Native child CPU is separately measured; archive CPU/wall costs are separately
retained. Hardware energy is not measured. Failure and development logs remain
separate from formal study results. Initial development rejected an invalid
eight-wide/eight-active transport profile; the original native guard was
retained and the profile corrected to satisfy it. That failed attempt is
preserved in the preflight test history.

The preflight fixtures establish connection, lifecycle and recovery behavior.
They are development-only known-action policies and do not constitute evidence
of task utility, quality, efficiency or superiority of the HCSN architecture.
