# Real trained Joint: original Torch versus native oracle

The historical trained descendant passes an independent comparison against the
unchanged original Python `JointGenerator` and `native_bridge.reference_tensors`.
The accepted replay-r3 artifacts were read only. No model, trained parameter,
accepted qualification file, or repository Rust source was changed.

## Result

| Comparison | Observed maximum absolute error | Threshold fixed before execution |
| --- | ---: | ---: |
| Native FP64 versus original Torch FP64 | 3.9968028886505635e-15 | 1e-9 |
| Native FP64 versus original Torch FP32 | 7.407944591086846e-7 | 5e-5 |

The comparison includes 20 recorded native helper states, each containing
16 inspected tensor groups and 5,283 scalar values. Each is compared with both
original Torch precisions, producing 40 comparisons. The inspected groups are
context, shared state, modality slots, feedback, all four recurrent core fields,
four output heads, actor logits, policy probabilities, critic and delivery critic.
Discrete step, stop and content/verification revision fields also agree.

The 20 states comprise the nine-state accepted action schedule for each native
sampler and one Auto successor for each sampler. A further nine fresh mean-mode
helper proposals reproduce the accepted state, prefix and stopped bytes exactly.
The fresh schedule uses seed 17, shared refinement, a 16-unit audio prefix commit,
image/audio/video/text refinement, verify and stop.

All four mean-mode output payloads are byte-identical to the original Torch model
in both FP64 and FP32, after the ABI's documented image/video uint8 and audio PCM16
serialization. The audio comparison preserves the early committed 16 samples and
uses the final state only for the remaining samples. Payload sizes are 768 image,
2,048 audio, 3,072 video and 17 text bytes. Mean text is `action=1;sound=1` followed
by a newline. The earlier native SplitMix output is `action=1;sound=2` followed by
a newline.

Original Torch FP64 and FP32 both select `stop` for the tested initial-state Auto
query; both actual native sampler successors match the independent original
model's selected transition. This establishes the tested policy decision, not a
planning benefit.

## Source and checkpoint binding

The same real checkpoint was loaded using `torch.load(weights_only=True)` and
`load_state_dict(strict=True)`. Its complete Joint tensor digest matches the
historical recovery manifest before and after the experiment. Reexport through
the unchanged original exporter reproduces both native weight and public packets
byte for byte:

| Artifact | SHA256 |
| --- | --- |
| Trained checkpoint | `33c1aa759bddb5e9b33b906e1796de7a6f89e5b5916711f99033584b3cbafb97` |
| Native weights | `41ce6de8a9095e1ef6b8756c3117a160ed40acfad8b297390de95083664d223e` |
| Native public input | `86c55417fdf2abdd065fc9828c40260aed0ded4a0d607c551e15b2f6b5fd2c00` |

All six copied Python sources match the historical manifest at
`18dac3ccd30317893ad922792c12400390522f00`. The four copied native numeric modules
match the accepted build at `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`.
`inspect.rs` is a small read-only adapter: it decodes saved actual helper states
and calls the existing `Model.inspect`. It does not implement another model or
modify the helper. One isolated inspector compilation and one batched inspector
process are included in the recorded costs. No Cargo/workspace CI was run.

## Scope

This closes the previous missing independent numeric oracle for this trained
descendant, input, sequence and native math profile. Native SplitMix and original
Torch use different explicitly named random sampling laws; equal seeds do not
establish equivalent stochastic emission bytes. Their content states and decoded
logits are compared here. Random-media cross-implementation equivalence remains
unestablished.

The input is still the historical synthetic mechanism sample `[3]`. There is no
natural multimodal quality claim, optimizer-resume claim, new training, restored
original-parent-byte claim, or Agentd cancellation/durable-adoption claim.

## Cost boundary and evidence

The outer observed process envelope, including startup, Torch imports, source and
asset checks, inspector compilation, strict checkpoint load, same-source reexport,
nine fresh helper calls, one batched inspector call, original Torch calculations,
raw evidence writes and teardown, took **7.447762378 seconds wall** and
**9.383129 CPU seconds inclusive of waited descendants**. These totals overlap the
inner ledger and must not be added to it. The nine helper calls transferred
43,832,120 stdin/stdout/stderr bytes.

`run-r1/ORACLE.json` retains the narrower inner totals and stage costs. Both the
compiler CPU and the actual helper CPU are charged. Energy, physical disk traffic,
historical training costs, initial read-only discovery and code authoring were not
instrumented. The peak RSS in the outer receipt is an execution-tree high-water
measurement, not isolated helper memory. All inference and build work in this
experiment is recorded; unmeasured categories are not assigned zero.

`EVIDENCE-INDEX.json` binds the compressed raw-evidence archive. The archive retains
the executed harness, inspector adapter, exact historical Python and native Rust
source copies, all inspected native packets, both original Torch reference
packets, fresh helper responses/states/prefixes, media payloads, build logs and
cost receipts. Checkpoint/native asset bytes already fixed by the previous stage
and the rebuildable inspector executable are excluded from this compressed
archive and listed with their hashes in its index. They remain available in the
experiment directory or their recorded input locations.

## Published source snapshot

The readable `inspect.rs.txt` preserves the exact executed inspector bytes as an immutable evidence snapshot. The archive retains its original runnable name `run-r1/inspect.rs` with the adjacent native-source modules. Native product code is unchanged. The snapshot harness retains exact execution-environment paths.
