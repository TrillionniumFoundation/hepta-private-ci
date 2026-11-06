# Independent H3 review: retained executable identity and runtime input migration

**Result: no concrete static blocker found in the seven-file v1 candidate.** This is a source and interface review, with local static comparisons only. It gives no Rust compile, formatter, native test, process recovery, model execution, or H3 qualification credit.

The reviewed base is Hepta `620cb63ae9b58904483005bcb2c4e1507df99539`, tree `f2cebe6d99deca596c170922b8e60d66648d7393`. The candidate patch is `938124f6dffe9127463e5bf93b473d6f58e07567aa5a78ff90b07ee38b9f7fb8`; its manifest is `94e38205ffc44e2a4af1571fee1d70d379737e1d403af756f812fee61476d257`. These are pre-format bytes. Final formatting, a frozen H3 source identity, and actual execution remain separate requirements.

## 1. The H2 failure and the assertions still owed

H2's ordinary process case timed out at 60.007 seconds. Its wrapper exited 100 after 71.727312918 seconds, without reaching its 1800-second outer timeout. The actual retained evidence shows the first owned process was captured, the provider fsync barrier was reached with one physical apply and no delivered ACK, and the first owned process's SIGKILL was observed. The second process had begun image retention: its retained output was only 314,572,800 bytes of a 488,112,384-byte image. No second-process or completed checkpoint existed. This supports an unfinished second image-copy/hash loop; it does not separately attribute the delay to hashing CPU versus I/O.

The H3 change leaves the ordinary crash, current-owner, generation, lookup, nonce, and receipt assertions intact. In particular, all source bytes from the second-process checkpoint to the end of the main case are identical to H2. H2 did not complete that portion. H3 still must demonstrate:

- a distinct new PID/start-time identity using the same executable;
- rejection of the old client generation and old generation grant;
- no second provider POST or physical apply;
- the first temporarily absent lookup remaining Indeterminate;
- subsequent current-owner recovery of the original operation;
- a durable ACK and terminal receipt for the same operation and payload;
- the original FinalUse nonce count remaining one;
- owned second-process cleanup and the final completed checkpoint.

The prior H2 failure remains a failure. Source review and a reused image hash do not complete any of those missing assertions. The exact H2 raw bindings and reached/unreached boundary are retained in `../h2-process-timeout-review/review.json` (SHA256 `30fbf6f3d8fbb2040739429ee445b25485baff45d879846751521ffd4328fb37`).

## 2. Held executable reuse is tied to an actual file object

`tests/support/automation_effect_binary.rs` now returns a `LiveDaemonImage` that keeps the actual first executable file descriptor and the completed retained-copy descriptor alive. It also retains their device, inode, length, mtime and ctime, including nanoseconds. The first ordinary process still performs the full read, SHA256, copy and sync. The second ordinary process independently opens its actual `/proc/<pid>/exe`; it cannot reuse an earlier hash solely by matching a path.

Before reusing the first digest, the helper requires the same source record and all of these identities to agree: the current Cargo-resolved path, the current process's opened executable descriptor, the still-held original executable descriptor, the retained path, and the still-held retained descriptor. Both held file objects must retain their original full metadata; the copy must have the full executable length. The helper repeats the relevant comparisons after capture, independently checks PID start time, argv and the process executable, and preserves the owner ID and generation checks. A held descriptor prevents inode recycling while the comparison is being made.

The main case keeps the first `LiveDaemonImage` in scope through the second capture. The second result retains its own executable descriptor and a cloned retained-copy descriptor. New receipt fields explicitly distinguish `first-live-fd-hash-copy` from `same-held-file-object-reuse`, record the originating capture PID/start time, and set `full_hash_and_copy_this_capture=false` for the reuse case. This avoids pretending that a second full hash was computed.

This is an ordinary filesystem identity argument in a controlled, nonconcurrent-build window. It is not a sealed executable namespace or a guarantee against a privileged writer able to defeat filesystem metadata assumptions. That limitation is explicit in the candidate receipt. Removing the repeated large copy is reasonable within this scope; static review cannot establish that the complete case now fits 60 seconds.

The added short control exercises a successful same-object comparison, then independently rejects an equal-byte different inode, modification of the held image, and disappearance of the completed copy. Those fixtures are inert ordinary files, not actual executable-attribution evidence. The original process test supplies the actual executable and restart validation.

## 3. The constructor migration preserves the runtime boundary

The current `SmolLmNeuralReadConfigV1` requires `runtime_snapshot` bytes and a complete source-pin set. Two integration-test constructors had not migrated. H3 corrects their distinct roles without changing the production runtime validator or model authorization APIs.

### Opt-in real comparison

The controlled comparison input becomes `hepta-smollm-neural-comparison-native-v2`. The snapshot path and SHA256 are mandatory serde fields; there is no default, automatic capture, or v1 fallback. `read_runtime_snapshot` requires the existing project paths and the snapshot to be absolute. The snapshot must be a canonical regular, nonempty file of at most 16 MiB and match the independently supplied nonzero SHA256. The opened file is checked as regular with the admitted size; the actual read is capped at limit plus one and the returned bytes must match the pin. The JSON must declare `hepta-controlled-cold-runtime-snapshot-v2`.

These exact bytes are read once before creating the comparison output/ledger or either model and are passed to both model constructors. This is admission of pinned input bytes, not a claim to hold the later runtime inventory immutable. The existing production worker still verifies the interpreter, runtime inventory, source bytes, original deadline, and cancellation before execution.

The constructor now supplies exactly the 13 source/configuration basenames required by the current profile, including the previously omitted contract wire, base material, Python runtime contract and four configuration files. The independent static check compares the full set against exact H2 `smollm_neural_profile.rs`, rather than checking only a count. The profile commits the snapshot digest, all source digests, action labels, model and contract identity. The controlled test issuer and original gen2/gen3 comparison logic are unchanged. The opt-in real comparison remains ignored without explicit operator input; this migration does not run or authorize a learning trial.

The new input control tests a complete inert v2 input, old-schema refusal, missing snapshot fields, a relative path, a mismatched digest, and an oversized file. It does not execute its fixture interpreter or a model. Creation of comparison/model output remains absent in that control.

### Existing qualification-negative constructor

`neural_cognitive_bootstrap.rs` adds an intentionally empty snapshot only to `ordinary_native_composition_rejects_untrusted_qualification_before_inference_owners`. Its assertion remains rejection at the original untrusted product-qualification boundary before any runtime owner, worker, journal, material or issuer is created. The empty value cannot qualify a positive runtime: exact H2 `snapshot_digest` still rejects empty bytes, and the existing `pre_spawn_requires_the_declared_interpreter_and_nonempty_contract` source has that explicit negative assertion.

## 4. There is a real snapshot producer, with a limited claim

I independently fetched and hashed these three files at exact H2, saving the original GitHub responses and the byte-identical sources under `exact-h2/`:

| Exact source | Git blob | What it establishes |
| --- | --- | --- |
| `scripts/hepta_smollm_runtime_snapshot.py` | `d2bbe33a4ab55dd9c816eb7ea0b7cef07c4cf6c6` | Existing v2 snapshot producer and verifier |
| `codex-rs/hepta-infer-worker-host/src/smollm_python_runtime.rs` | `72dddae726fc10a8f78b5d45984c3bfcbb5986ed` | Nonempty snapshot, interpreter and complete runtime inventory admission |
| `codex-rs/hepta-infer-worker-host/src/smollm_python_runtime_tests.rs` | `c11ea44a750d6ecfb9a7a2dcf558d324b7c4460b` | Existing empty/missing/replaced runtime rejection controls in source |

The producer's `record --lock --installation --output` entry requires a private CPython 3.12 environment launched with `-I`, the fixed original CPU requirements digest, complete exact wheel/install-report bindings, distribution RECORD validation, and the managed file inventory. It records actual preflight imports and selected mapped libraries and writes the snapshot plus its SHA256. An operator can retain that result before a separately authorized comparison. H3's documentation accurately identifies this existing producer; the comparison consumer does not invoke it.

The producer itself labels the result `immutable_held_runtime_closure=false`, `actual_model_execution=false`, and `production_qualification=false`. Neither producing nor accepting a snapshot establishes later model execution, full model cold adoption, independent quality improvement, current PQ authority for a generic model sink, or a sealed runtime. The comparison's controlled issuer remains a test composition.

I additionally fetched the exact H2 workflow and three constructor-related base files independently. Their returned Git blobs and bytes match the candidate's declared bases; details are in `exact-base-fetch-verification.json`. The two process/helper bases were already exact-H2 bound in the process-timeout review and candidate provenance.

## 5. Persistent CI wiring and unchanged original limits

The independent static check found 71 original exact names retained and 74 selected names after this change. The product gate adds the held-file negative control and changes its minimum from one to two, with its original 1800-second wrapper unchanged. A new separate gate selects the input-v2 control and the existing qualification-negative control, minimum two, wrapper 600 seconds. Its two integration targets compile through the same `just test --locked` route.

All original step relative ordering, commands outside the required product selector/minimum change, matrix, environment, lane selection, resources, retries, single test thread, and the 90-minute job remain unchanged. The original per-test 60-second nextest bound is not edited. After removing only the expected-name dictionary, the exact-name guard's AST is identical: actual logged cases, count, success, original raw SHA, and no skipped or failed selected cases remain required. The new names resolve to actual nonignored source tests; the real model comparison remains ignored.

`check_static_bindings.py` and `static-bindings.json` retain the independent assertions. The first two local checker runs failed in the checker itself because the workflow also contains unnamed action and run steps; the first accessed a missing `name`, and the second assumed all unnamed steps had `uses`. Both traces are retained. Stable anonymous-step keys fixed this local inventory bug; the third static run passed. No candidate source, gate, test assertion, budget, or native result was changed by these local checker repairs.

## 6. Remaining decision boundary

The review supports proceeding to the original formatter, exact final-source freeze, and native gate sequence. It does not substitute for them. H3 must actually complete the ordinary process case in the original 60 seconds, execute all 74 selected cases, preserve source/config/lock/toolchain identity, and satisfy the remaining evidence library, Clippy/fix and format gates under their original budgets. The selected snapshots, fixture issuers and controlled process services do not close generic tool/provider current-PQ composition, full-host recovery, independent custody, learning quality, or WAN release qualification.
