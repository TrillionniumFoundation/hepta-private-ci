# Independent review of the current neural-study input boundary

**For exact Hepta H3 `6db78eca53a5acdda0d96873d3f4cd65863426f0`, the workflow's currently generated v1 input is rejected before a new study ledger, final-holdout journal, or training helper is created.** This conclusion comes from source inspection. No workflow, model, learning trial, Rust compilation, native test, or desktop command was executed for this review.

## Exact source binding

I independently fetched the workflow, the ordinary input loader, both ordinary selected entry points, and the study entry at H3, checked their returned Git blob hashes, and compared their contents with the H2 sources. All four are unchanged:

| File | Exact Git blob |
| --- | --- |
| `.github/workflows/hepta-neural-study-v1.yml` | `87b4482f5d4ae73d662f796b92e92036adce6fdf` |
| `smollm_initial_host_tests.rs` | `752861c2603ffb9b53e3bc5888370865ab70fb45` |
| `smollm_initial_agentd_tests.rs` | `2b8d02fdc93a82f6e6b1c2c8acbef1357f1b4436` |
| `smollm_neural_study_tests.rs` | `299f9b651a7a2a2fd2edcc5b7e7860c83382eb17` |

The Rust files are under `codex-rs/hepta-infer-worker-host/src/`. Original responses and the exact H3 binding are retained beside this review. I also independently hashed the six inherited W1 source copies against their exact H2 API payloads, including the study roles and final-holdout implementation. This does not independently attest GitHub run history; W1 retains that separate API evidence.

## The generated input cannot reach model/study creation

The workflow's `materials` step writes an inline config with schema `hepta-smollm-neural-native-check-v1`. Its fields include Python, Chain, materials, parent, parent SHA256 and output. It omits `runtime_snapshot` and `runtime_snapshot_sha256`. A separate environment variable points to a runtime snapshot, but the Rust deserializer does not read that environment variable or inject those missing JSON fields.

`smollm_initial_host_tests.rs::NativeInput` derives `Deserialize` with `deny_unknown_fields`. Both snapshot fields are mandatory concrete `PathBuf`/`String` fields, with no `Option`, `default`, or custom deserializer. `input_and_worker` first reads `HEPTA_PN3_NEURAL_NATIVE_CONFIG`, then immediately executes `serde_json::from_slice(...)?`. Missing fields therefore return an error before its schema-v2 assertion, parent descriptor read, source-pin collection, output creation or worker construction. Even a v1 input with the two fields manually added would still fail the following unconditional v2 assertion.

The two ordinary tests selected by the workflow are not alternate paths around that loader:

- `real_public_initial_reopens_same_ordinary_owners` begins with `input_and_worker("public-reopen-session-0")?` before creating its root and owner fixture.
- `real_selected_initial_serves_ordinary_context_then_refuses_revocation` begins with `input_and_worker("ordinary-selected-initial")?` before creating its owner fixture.

The study's selected test calls `run_study(StudyProfile::OriginalV1)`. The first statement of `run_study` is `input_and_worker("positive-parent")?`; its own study-root directory is created only after that succeeds. The explicit training ledger is later created through `roles.dataset(..., root.join("training-ledger"), ...)`. The Python training helper is launched after the ledger and preregistration material. Final-holdout creation occurs still later in `evaluation::evaluate`, which the study calls after its training result. The input rejection precedes all of these operations. The other study profiles share the same first loader call.

This is stronger than relying only on workflow step conditions. There is also a second condition chain: `ordinary` is not marked continue-on-error; `study_controls` requires `success()` and ordinary success; Cell and source-before require their preceding steps; the training step requires success and source-before success. The current malformed input cannot produce the successful ordinary results required by that chain. No missing-field fallback, catch-and-continue, or direct earlier study-helper invocation was found in these exact entries.

## Scope of this conclusion

The workflow still declares pull-request path triggers that include `codex-rs/hepta-agentd/**`, plus manual dispatch. It has no push trigger or explicit draft-PR exemption in the inspected source. Before the failing ordinary input is reached, a workflow run can still build prerequisites, compile Rust, install a runtime and fetch/prepare model materials. This review does not claim a triggered run is free or that no CI job will start.

The refusal is a current producer/consumer incompatibility, **not a durable authorization or cross-run spent-ledger mechanism**. Updating that producer to valid v2 input would change the reachability conclusion and would require a new explicit learning authorization/review. Likewise, a manually supplied valid input can reach the opt-in study when separately invoked. Neither case is authorized or executed by this review.

The study code uses fresh local study roots and later creates fresh training/holdout records; this narrow review does not treat them as continuity with a previously consumed study. W1 owns the broader budget, prior-spend and trigger report. No source was changed to bypass the current refusal, and no trial, seed, ledger, holdout, model result or authority root was created here.
