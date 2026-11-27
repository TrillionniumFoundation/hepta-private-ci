# Completed baseline36 plus C1: independently audited D results

D is development/tuning data. One common LR is selected by the mean macro-F1 over all three seeds. Both declared LR rosters and all C1 phases are charged. HCSN is excluded; no full42 or scientific-benefit claim is made.

| Core | Common LR | Mean D macro-F1 | Seed range | Mean accuracy | Mean NLL | Adequate selected chains | All6 + C1 active process seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| gru | 0.003 | 0.424975 | 0.412045–0.432334 | 0.727946 | 0.952863 | 3/3 | 784.262771 |
| cfc | 0.003 | 0.349025 | 0.330602–0.360342 | 0.662535 | 1.177879 | 3/3 | 1701.856524 |
| snn_plif | 0.003 | 0.149979 | 0.112659–0.169318 | 0.465073 | 1.909887 | 3/3 | 1308.998034 |
| event_time_lif | 0.003 | 0.313031 | 0.283081–0.360945 | 0.627712 | 1.230212 | 3/3 | 3926.968261 |
| ssm_s4d | 0.003 | 0.366866 | 0.347751–0.394162 | 0.615548 | 1.332454 | 3/3 | 817.097920 |
| attention | 0.003 | 0.402617 | 0.346441–0.432450 | 0.677099 | 1.072262 | 3/3 | 1461.600457 |

The original v1 review remains overall failed on a two-sample clock identity. This supplement preserves every raw time, verifies ordered finite sampling intervals, and uses the original later cumulative observation time for all cuts. Original36 hashes and six prior fresh forwards are reverified, with no original training/forward replay. Seven C1 selected checkpoints receive fresh original-v8 no-grad forward checks.

The three memorization failures remain: snn_plif-s101-lr0.001, cfc-s211-lr0.001, snn_plif-s307-lr0.001.

Reported child CPU samples precede final serialization. Exact C1 waited-child CPU is an aggregate including its preflight. Active process-wall sums are not elapsed calendar time; energy is unknown.
