# Direct two-host update using real SmallHCSN features

The external-statistic hook has now been exercised with the real pinned SmallHCSN implementation. Both physical hosts independently generated their local synthetic training batches, executed the frozen physical model, and formed their local readout statistics. They then exchanged those statistics directly over the same qualified USB4 SSH transport and independently obtained the same readout candidate.

The common model is a reproducible new frozen initialization for each width and seed. This experiment updates the difference of the two class readouts and an intercept. It leaves all nonlinear physical and recurrent parameters unchanged. It does not train a language model or recover its entire weight field.

## Frozen study and data separation

The provider protocol is `../actual_p2p_v2/PROTOCOL.json`, SHA256 `5d5e6193ff962ded6e912238f0f87ea969d362bbd7345cf0885f9625c81c89c1`, originally anchored by Git commit `4c40e8a7b11a1f2afd661f2b76dd3929a3f41edb`.

The roster is four neuron widths, 8/16/32/64, and three new seeds, 271901–271903. Because the actual readout uses receiver neurons, the trained coordinate dimensions are 21/41/81/161. Each physical host generates four independent-source batches of 32 training examples per case. The two hosts differ in late-input support and nuisance distribution. They share one serialized feature basis obtained from an independent unlabeled calibration corpus before training.

The common coordinate transformation is `X = [(features - mean)/scale, 1]`. The physical parent readout is represented in those coordinates, and every local right-hand side is the residual moment `X.T @ (y - X @ parent)`. Both hosts charge the same ridge prior once after pooling sufficient statistics.

All twelve peer candidates were completed before the independent transport/numerical audit. That audit imports neither the feature provider nor its corpus generator and does not generate or read test data. The orchestrator subsequently sealed all candidates and exact result hashes in Git commit `e725f22b5c9806fb1ebb33845085195926a993b4` before opening the separately frozen evaluator. This archive contains the pretest transport and numerical evidence; model-quality evaluation is maintained by the separate actual-model study.

## Audited outcome

| Measurement | Observed result |
| --- | --- |
| Two-host cases completed | 12 of 12 |
| Independent checks | 33 per case, all passed |
| Original local provider files reconstructed from retained peer statistics | 24 of 24 matched their original exact byte SHA256 |
| Candidate and action agreement | Both raw lists equal; each node's candidate content hash independently verified |
| Shared physical parent and serialized coordinate basis | Identical across the two nodes in every case |
| Actual remote exit and restart | Exit 17 followed by exit 0 in every case |
| Exact crash checkpoint and new-PID recovery | Verified in every case |
| Application frame bytes, both directions | 40,042,839 |
| Frame hash and byte conservation | Exact in both directions |
| Maximum independent NumPy relative action difference | 1.2580727370995353e-10, below the predeclared 1e-7 gate |
| Maximum relative normal-equation residual | 5.821676675447782e-14, below the predeclared 1e-10 gate |
| Protocol supervisor elapsed time | 42.46561168273911 seconds |
| Protocol launcher through process completion | 42.51107239210978 seconds |

The same independent audit was also executed with `python3 -O`. All twelve cases and all 33 checks passed; substantive results were identical after excluding newly measured audit runtime. The original published pretest report bytes were preserved.

## Measured cost

The physical-feature provider ran separately before the peer protocol. Its complete launcher elapsed time was 22.516 seconds on `pocket4` and 29.370 seconds on `ai395`; the corresponding inner provider loops were 20.515 and 27.298 seconds. Those node intervals overlap, so adding them would not represent system wall time. Shared calibration, dependency setup, deployment, and subsequent evaluation are additional separately recorded stages in the main study.

| Neurons | Readout dimensions | Mean solve on pocket4 | Mean solve on ai395 | Mean initiating-node protocol time through result readback |
| --- | --- | --- | --- | --- |
| 8 | 21 | 0.813 ms | 0.381 ms | 1.059 s |
| 16 | 41 | 2.849 ms | 3.525 ms | 1.473 s |
| 32 | 81 | 12.821 ms | 20.114 ms | 2.899 s |
| 64 | 161 | 68.872 ms | 108.327 ms | 8.715 s |

At dimension 161, mean local data/feature preparation was 3.267 seconds on `pocket4` and 4.010 seconds on `ai395`, while `G,b` formation itself was about 0.581 and 0.626 ms. Those provider measurements are carried in the protocol records as provenance but are outside the protocol wall interval. The protocol includes two SSH sessions per case, a deliberate 0.35-second restart wait, repeated frames, admission, JSON serialization, and durable checkpoint/readback work. A small analytic solve is only one stage of the system.

The application-byte counters exclude encryption, network headers, and retransmissions. Phase counters include overlapping waits and are not additive across hosts. The complete protocol launcher time is the reliable elapsed interval for this phase. Archive packaging and evidence retrieval happen afterward and do not constitute additional training.

## Evidence layout

- `results/pft2_real_hcsn_pretest_audit.json` is the unchanged report sealed with the candidate publication; SHA256 `6732dca9f5012522ef01a8bb4f3aae11979d842cc00ab8cc190d394309ef306c`.
- `evidence/actual_hook/provider_manifests/` contains the two original local provider manifests.
- `evidence/actual_hook/archives/` contains both exact host archive manifests and all ordered binary parts. The manifest binds every logical archive, every part, and every contained result/statistics/checkpoint file.
- `evidence/actual_hook/pretest_candidate_roster.json` connects widths, dimensions, seeds, candidate hashes, and both result hashes. It is an audit-derived roster; the external seal is the separate Git publication.
- `evidence/actual_hook/execution_receipts.json` records complete durable provider, peer-run, and packaging terminal states.
- `evidence/actual_hook/optimized_audit_gate.json` records the optimization-mode audit comparison.
- `ACTUAL_HOOK_INDEX.json` enumerates public evidence paths, byte counts, and SHA256 values.

There are 51 binary parts totaling 17,213,548 bytes. Each is at most 480,000 bytes. For a split logical archive, concatenate its `parts` in manifest order, verify the whole archive SHA256, then read the tar.xz contents. `audit_hook.py` performs that reconstruction in memory and independently verifies each original provider artifact, both candidates, the full packet counters, the crash checkpoint, and the centralized normal equations.

```sh
python3 audit_hook.py \
  --archives evidence/actual_hook/archives \
  --protocol ../actual_p2p_v2/PROTOCOL.json \
  --provider-manifests evidence/actual_hook/provider_manifests \
  --output /tmp/real_hcsn_peer_audit.json
```

The qualified transport is between two registered, authenticated physical hosts. Provisioning and candidate publication still use an orchestrator. This is direct peer computation for a shared frozen basis and learned readout, with explicit recovery and numerical equivalence; it is not evidence of permissionless or Byzantine-resistant federation, nor of full nonlinear field training.
