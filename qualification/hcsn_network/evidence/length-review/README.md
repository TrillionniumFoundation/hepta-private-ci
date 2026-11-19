# Independent read of the network length profile

This review reads the existing eight profile artifacts from source PR #6754, commit `8fe7bc209803659cc3f4780be0940c5183ca6e9b`. It creates no model, does not call forward, backward or an optimizer, and does not generate a trajectory. The independent waiting-mass reconstruction performs **32 new SciPy matrix-integral actions** on saved pending-flux records. Zero model calls does not mean zero numerical work.

## Source and execution custody

- Reader committed before execution: `84255edacfebf0c5f8c5645b99c9a5ef9743439f`.
- Reader SHA256: `edbbba83a7c131617d3d81180acdacc0f3881060756cad8e2116562359639632`.
- Protocol SHA256: `9601216e77b3dc5b3b41f77d7df8f124b7ab176692b0a0b66f24773b95eec9e0`.
- `SOURCE.json` froze all 67 original files, totaling 1,297,344 bytes, before the unique reader execution `attempt001`.
- All 25 protocol-pinned source files and all original artifact hashes were checked before and after reading. All eight process requests, exit statuses, stdout/result pairs, cost records and output rosters agree.
- Reader resource scope: CPU 8, one numerical thread, 4 GiB address-space limit, 60/65-second CPU limits, 90-second wall deadline. One execution, exit 0, no timeout or scientific rerun.

## Findings and limits

The artifact, shape, full dynamic-state payload and original absolute balance checks pass for all eight cases. This status does **not** impose or claim a newly invented approximation-accuracy gate. It does not close the scientific research program or upgrade any older failed gate. `all_closed` remains false.

Across all cases, 280 tensor records containing 123,444 coordinates match between `state.pt` and the corresponding `RAW.npz` entries, byte for byte. Their total logical payload is 987,552 bytes. These are custody counts, not independent observations or samples. The reader enumerates every tensor in the saved record, checks field and tensor shapes, reconciles ZIP storage payload and serialized file size, and reconstructs both layers' probability and all eight signed-content balances. The largest residual is `1.3766765505351941e-14`, within the original `2e-9` gate.

A state file retains the complete **dynamic forward state**. It does not include the classifier weights, the externally supplied physics, the optimizer, or the prior autograd graph. This review checks saved-state custody; it does not run a cold continuation or repeat gradient verification.

### Dynamic state and storage

| Steps | Flow logical bytes | Erlang4 logical bytes | Flow serialized bytes | Erlang4 serialized bytes | Flow pending packets, both layers | Largest saved flow generator |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 20,384 | 2,304 | 34,311 | 8,493 | 8 | 15 |
| 20 | 57,984 | 2,304 | 72,455 | 8,493 | 8 | 25 |
| 40 | 193,984 | 2,304 | 208,135 | 8,493 | 8 | 50 |
| 80 | 705,984 | 2,304 | 720,071 | 8,493 | 8 | 100 |

Each arm also reports 560 bytes of logical physics views; the Erlang4 arm reports 3,168 bytes of transition/integral/generator views. Those views count repetitions and are separate from dynamic-state payload. They are not measurements of unique allocated storage. The fixed number of pending flow packets does not imply fixed memory: the nested generator dimensions grow with the horizon.

All lengths use the same `dt=1/20`. Horizons are 0.5, 1, 2 and 4, with a single seeded synthetic sequence and batch 1. This is length scaling over shared prefixes, not time-step refinement, a continuum result, an arbitrary-history result or a task benchmark.

### Approximation deviations

Define `delta = Erlang4 - flow`. The two normalization denominators are the **entire corresponding flow observable**:

- `relative_linf = max(abs(delta)) / max(abs(flow))`.
- `relative_l2 = norm(delta, 2) / norm(flow, 2)`.

There is no denominator floor; a zero denominator would yield JSON null. None is zero here. The gradient objective is the executed profile's `sum(logits**2)`. Parameter gradients contain 259 flattened coordinates in the shared constructor's parameter order; input-gradient shapes are `[1, steps, 2]`. These are one initialization and one synthetic sequence, not 259 or 160 independent experiments. Erlang4 changes the waiting-time law, so these deviations measure a model approximation rather than floating-point solver error.

| Steps | Observable | Max absolute deviation | Flow L-infinity denominator | Relative L-infinity | Flow L2 denominator | Relative L2 |
|---:|---|---:|---:|---:|---:|---:|
| 10 | logits | 0.0005744149436 | 0.243690066 | 0.002357153712 | 0.5346123835 | 0.001943912345 |
| 10 | parameter_gradient | 0.001148829887 | 0.4873801319 | 0.002357153712 | 1.083129004 | 0.003742542239 |
| 10 | input_gradient | 0.0005297137389 | 0.02072993511 | 0.02555308234 | 0.04308785943 | 0.02992766564 |
| 20 | logits | 0.0005787781487 | 0.2748427305 | 0.002105852127 | 0.5629534034 | 0.002025213621 |
| 20 | parameter_gradient | 0.001157556297 | 0.5496854611 | 0.002105852127 | 1.186812401 | 0.003896114538 |
| 20 | input_gradient | 0.001256803782 | 0.05181951658 | 0.02425348334 | 0.1420016983 | 0.01853252732 |
| 40 | logits | 0.0005583156706 | 0.343267484 | 0.001626474095 | 0.6066146931 | 0.001430906108 |
| 40 | parameter_gradient | 0.001249711541 | 0.686534968 | 0.00182031739 | 1.445162608 | 0.002876637546 |
| 40 | input_gradient | 0.002172665226 | 0.1086737104 | 0.01999255587 | 0.4321227377 | 0.009932043821 |
| 80 | logits | 0.0007432445263 | 0.5088366058 | 0.001460674248 | 0.7253051774 | 0.001596179469 |
| 80 | parameter_gradient | 0.002699151946 | 1.017673212 | 0.002652277682 | 2.730157516 | 0.002997305437 |
| 80 | input_gradient | 0.009435892999 | 0.4704336734 | 0.02005786051 | 1.752543966 | 0.007815328355 |

The saved logits show relative L2 deviations of approximately 0.14–0.20%; parameter gradients 0.29–0.39%; input gradients 0.78–2.99%. Those are descriptive values for this one profile. No accuracy tolerance, confidence interval or broad training-equivalence conclusion follows from them.

### How strongly is the same-weights premise supported?

The frozen source explicitly sets `torch.manual_seed(101)`, calls the same `FlowClassifier` constructor for both arms, then converts to float64. The arm name selects a forward path without changing constructor parameter creation. A distinct generator seeded 123 creates `[1,80,2]` inputs before slicing each prefix; there are no optimizer calls. The retained process records point to this same source.

However, the profile did not save parameter values/hashes or input values/hashes. **Direct bitwise equality of the actual original weights and input prefixes cannot be checked from these artifacts.** This review reports same-seed and shared-source provenance, not a stronger artifact-level same-weights proof. It does not rerun a model to fill that evidence gap.

### Cost accounting

| Steps | Flow saved-tensor payload with repeats | Erlang4 saved-tensor payload with repeats | Flow full-process peak RSS KiB | Erlang4 full-process peak RSS KiB |
|---:|---:|---:|---:|---:|
| 10 | 721,897 | 88,537 | 225,764 | 224,496 |
| 20 | 3,503,177 | 163,977 | 228,032 | 225,404 |
| 40 | 21,145,097 | 314,857 | 235,824 | 227,176 |
| 80 | 145,236,937 | 616,617 | 277,448 | 230,884 |

The saved-tensor counter accumulates hook payload, including repeats. It is **not peak live tensor allocation** or allocator peak. RSS is the parent-recorded full-process Linux `ru_maxrss`, including runtime/import overhead, and is a different quantity. Full-process times include imports, source/runtime checks and serialization; forward/body timers cover a narrower interval. The flow forward timer includes conservation reads, while its `exact_forward_exponentials` counter is captured before the separate conservation integrals and therefore omits those actions.

The reader itself has separately retained costs:

- Body: 0.075903385994 seconds wall, 0.075325019000 seconds CPU. This starts after NumPy/SciPy/Torch imports and thread setup and ends before report/CSV serialization.
- Entire fresh reader subprocess: 2.461332070998 seconds wall, 2.435018000000 seconds CPU (1.845639000000 user + 0.589379000000 system), peak RSS 223,652 KiB. The parent uses `wait4`; this includes startup/imports, checks, 32 independent matrix-integral actions, writes and shutdown.

No repeated timings or statistically established speedup are inferred. Raw readable state/cost and deviation tables are supplied as CSV for later figures; this task rendered no figures during the parent benchmark.

## Retained files

- `review.py`: frozen independent reader and subprocess cost controller.
- `SOURCE.json`: pre-execution reader identity and original-file hash manifest.
- `attempt001/REVIEW.json`: complete tensor inventory, independent balances, deviation metrics, scope and body cost.
- `attempt001/COST.json`, `REQUEST.json`, `stdout`, `stderr`: complete reader process accounting.
- `attempt001/state_and_cost.csv`, `approximation_differences.csv`: figure data, with explicit field names.
