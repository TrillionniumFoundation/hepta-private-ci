# Frozen full-network long-stream numerical check

The registered `risk_margin_j_risk` classifier ran 4096 continuous `step` calls with one untrained seed, batch 1, width 32, eight physical channels and synthetic label-free inputs. Observation durations include zero, fractional intervals, and intervals requiring several numerical chunks. No heldout dataset was accessed.

| Check | Recorded result |
|---|---:|
| Completed observations | 4096 |
| Maximum probability mass error, measured in float64 | 4.470348358154297e-8 |
| Maximum mass error before correction | 2.434477210044861e-6 |
| Maximum actual L1 correction | 2.43261456489563e-6 |
| First-event probability range | 0 to 0.5620784163475037 |
| Maximum absolute content state | 0.8181833624839783 |
| Maximum absolute logit | 1.4034587144851685 |
| Save/load continuation at step 1024 | Logits and probability state bitwise equal for the next 16 steps |

All initial weights, generated inputs, per-step scalar diagnostics, probability distributions, content states, logits, and saved continuation states are retained. Expected event counts are accumulated in float64. The eight physical channels accumulated about 2124.29 expected events in total; this is a finite-state marked-process quantity, not a biological measurement or a count of sampled binary output spikes.

This extends the earlier kernel-only audit to the complete frozen forward network. It does not demonstrate trained long-context content quality, long-network gradients, generality across random seeds, biological fidelity, or accelerator efficiency. The exact input stream and durations are in REGISTRATION.json and inputs.npz.

A preceding audit-launch attempt failed before registration/model construction because a NumPy float32 tolerance was not JSON-serializable. Its source and failure receipt remain in the sibling `sixstage_20261030_network_long_stream` directory. The successful follow-up only changed the new audit's JSON literal conversion; no frozen model or numerical helper changed.
