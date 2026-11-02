# Separated finite mechanisms

This stage retains the inherited finite interval transition law. Each interval permits at most one new event; a refractory cell releases at the end of an interval. It is not the separate continuous-time CTMC and is not claimed to be an exact continuous Brownian renewal process.

Every cell candidate applies the same bounded voltage impulse immediately after a successfully completed READ. A missing packet does not inject evidence. An observation arriving while refractory remains available through the common public interface, but does not shift a refractory voltage. This common input operator remains fixed when either drift or the forecast driver changes.

| Factor | Levels | Exact intervention |
| --- | --- | --- |
| `drift` | `sustained`, `neutral` | Use the last completed observation or zero evidence in the interval transition. Neutral retains the fitted intrinsic drift bias. |
| `bank_driver` | `last`, `neutral` | Use the last completed observation or zero evidence only in the free-endpoint bank forecast. No transition changes. |
| `event_sign_readout` | `signed`, `pooled` | Preserve distinct lower/upper refractory feature rows, or replace both by their arithmetic mean. No transition or reset changes. |
| `reset` | `signed`, `common` | Preserve the lower/upper release distributions, or use their shared arithmetic mean. Event flux, refractory waiting probability and release probability remain unchanged. |

The sign intervention removes the explicit lower/upper refractory distinction from the readout. It does **not** erase all sign information: the common public observation, historical selection, and a signed reset can still carry information. The sign × reset panel permits these two channels to be examined separately. Its conclusions concern these declared interventions, not irrecoverable memory in general.

The drift × bank panel has four candidates. A sign × reset panel at the sustained/last input setting has four candidates and shares its signed/signed reference with the input panel. Two additional reference-cell candidates use single-snapshot or no policy feedback. Ordinary-bank multi-round and single-snapshot candidates share their physical law. The accumulator has all four free/structured head × off/multi feedback combinations, including the previously missing structured/off and free/multi cells.

All candidates initialize their common head coordinates and physical parameters from the same fit seed. The structured head learns the three continuation Q outputs and one belief logit. It fixes STOP to zero and derives the two submission values from that belief. The constraint ensures internal terminal consistency but does not ensure calibration, action ranking or utility.

The accumulator and sampled finite cells retain observations differently. Ordinary dynamics never reach refractory states. Pooled refractory rows have readout rank one although both allocated flag coordinates remain present. `capacity_report` records allocated, structurally active and trainable coordinates, physical trainability, and refractory readout rank; these quantities are not a proof of equal effective capacity. The training caller may freeze the physical parameters explicitly. Exported checkpoints record that choice and restore it.

`FactorRuntime` uses the same `representation` and `transition_for_context` operations as training, caches only fixed-model feature/transition tables, and evaluates the inherited head with NumPy. It is compatible with the original causal Python task executor. This stage does not add production Rust deployment.
