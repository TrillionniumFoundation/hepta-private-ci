# Free-text integration and independent development evaluation

This experiment adds a local, real causal language model to the Hepta output
state. Its output is unconstrained vocabulary decoding, not a sentence rendered
from the old two ontology indices. It does **not** establish broad open-domain
competence or natural audio/video generation.

## Executed contract

`JointGenerator.encode(public)` receives the actual source text through the
existing 128-entry character embedding. Other modalities carry zero availability
masks. The shared/text transition schedule produces a real persistent Hepta
state; `[shared, flattened slots]` is projected into two learned soft-prefix
vectors for frozen `HuggingFaceTB/SmolLM2-135M-Instruct`.

The complete original documentation and question also remain in the LM prompt.
The inherited character-mean encoder is a limited representation. We do not
claim that its state alone contains the document's meaning. Prefix and Hepta
content parameters are trained by teacher-forced language loss on four real
CPython documentation sources. Portfolio actors, critics, old media/ontology
heads and the pretrained LM are outside this adaptation update.
The resulting checkpoint is a text-development candidate. Changes to shared
content have not requalified the earlier media restoration behavior.
Zero-masked media branches still contain biases and shared fusion paths; their
nonzero gradients are not evidence that this run learned from image/audio/video
observations. The actual observed training modality here is text.

The model is reused in place from an existing local installation. The runner
checks every local model-file hash, pins its revision and weight hash, uses
`local_files_only=True`, and does not download or duplicate the 269 MB weights.

## Source and evaluation boundaries

- Fit modules: `json`, `textwrap`, `bisect`, `urllib.parse`.
- Public development evaluation modules: `statistics`, `functools`, `gzip`, `csv`.
- Exact docstrings, hashes, roles, questions, reference propositions, intervention
  arms and update count are written before training. Module sources are disjoint;
  their publisher is shared and pretrained-model exposure is unknown.
- Only the final update is evaluated. Evaluation does not choose a checkpoint,
  alter the training objective, feed rewards back, or access fresh calibration.
- State, zero-state and shuffled-state arms retain the same complete LM prompt,
  prefix length, maximum token budget and greedy decoding rule. Shuffling changes
  only the Hepta state, using another evaluation source's state.
- Evaluation occurs after every completion is fixed. A separate function sees
  only generated text and fixed factual predicates. It reports missing facts and
  flagged contradictions; it does not read latent state or neural losses.
- These narrow predicates are a transparent development diagnostic. They can
  miss semantic errors. `blind_review.json` contains unlabeled completions and a
  human rubric; ratings remain pending. `blind_key.json` is for later unblinding.

Any future confirmation requires new source families, a frozen checkpoint and
protocol, an evaluator independent of training and selection, and prospective
human/semantic assessment. This public development slice cannot become a fresh
confirmation set merely by renaming it.

## Run

From the repository root, using a Python environment with Torch/Transformers:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.open_domain \
  --model-path /tmp/cell-typed-convergence/consumer-materials \
  --checkpoint /path/to/study-checkpoint.pt \
  --output /path/to/new-open-text-evidence \
  --updates 16 --max-new-tokens 64 --threads 2
```

The checkpoint must contain `config` and `state_dict` compatible with the actual
JointGenerator. The output contains protocol, all raw completions, factual checks,
state intervention measurements, a small trained adapter/Hepta checkpoint, and
execution timing. Every state change is distinguished from a quality gain.
Phase timings include loading, adaptation, state encoding, LM prefill, decoding,
evaluation and evidence work. The JSON states that its `run()` clock excludes
Python imports; a surrounding single-child process meter supplies the full CLI
measurement for the executed development run.

Natural audio/video decoders are not available in the inspected local materials.
No tone, synthetic frame, label string or restored waveform is substituted for
that missing capability.

## Concrete next adapters for the missing natural modalities

These are specified integration candidates, **not implemented or executed
backends in this run**. Their weights, trained state adapters and independent
evaluators are absent locally, so their status remains `unqualified`.

| Modality | Candidate model/backend | State and output contract |
| --- | --- | --- |
| Natural audio | [`cvssp/audioldm2`](https://huggingface.co/cvssp/audioldm2), Diffusers `AudioLDM2Pipeline` | Learn projections from actual Hepta shared/audio state into the backend's `prompt_embeds` and `generated_prompt_embeds` conditioning; retain masks and native latent/scheduler state; emit real waveform plus sample rate, channel count and duration. |
| Natural video | [`Wan-AI/Wan2.1-T2V-1.3B-Diffusers`](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B-Diffusers), Diffusers `WanPipeline` | Learn a Hepta shared/video-state projection into `prompt_embeds`; retain native video latents and timesteps; emit decoded frames and encoded video with frame count, frame rate and duration. |

The documented conditioning interfaces are in the official
[AudioLDM2 API](https://huggingface.co/docs/diffusers/en/api/pipelines/audioldm2)
and [Wan API](https://huggingface.co/docs/diffusers/en/api/pipelines/wan).
Projection shape compatibility alone is insufficient: train the adapters using
real paired examples, record nonzero task gradients into Hepta content, and
compare state/zero/shuffle with identical public evidence and complete costs.
Before executing, freeze backend revisions, weight hashes, adapter parameters,
the complete source allocation and decoder settings. No weights are downloaded
by the present runner.

Both integrations need this separate evaluation record:

```text
input: artifact_sha256, source_family_id, task_spec, evaluator_manifest
output: semantic_facts, missing_facts, contradictions, temporal_consistency,
        naturalness_rating, evaluator_identity, uncertainty, actual_eval_cost
```

The evaluator receives the final media bytes and task specification, without
generator latent states, training losses or arm labels. Audio assessment must
check the requested events and their timing; spoken content also needs independent
transcription and intelligibility assessment. Video assessment must inspect
objects, actions and their temporal ordering across frames, not only pixel error
or isolated-frame appearance. Blinded listening/viewing complements independent
learned semantic assessors. AudioLDM2's own internal CLAP ranking is part of its
generation machinery and is not accepted as the independent evaluator. All
evaluation and codec work belongs in the cost record. Test-source families must
be isolated from adapter training and remain unused during model selection.

## Preflight failure retained

Before integration, the pinned local LM generated 65 free tokens in about 4.55
seconds on two CPU threads. Asked why a tire softens when air leaks out, it
incorrectly attributed the effect to degradation under high pressure and high
temperature. This is a factual failure, not evidence of task competence.
The exact continuation was:

> When a bicycle tire is subjected to high pressure and high temperatures, the
> tire's internal structure undergoes a process of degradation, leading to a
> decrease in its overall strength and flexibility. As a result, the tire becomes
> softer and more prone to cracking and damage when it is subjected to
> high-pressure and high-temperature conditions.

The integrated run's exact outputs and timing belong in its generated report;
successful loading or nonzero state sensitivity alone cannot close semantic
quality or global NDU efficacy.

## Measured frozen development run

The final run used the common study checkpoint
`matrix_frozen_20261030/seed-17-width-32/dual.joint.dynamic/MODEL.pt`, SHA256
`9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc`.
Its four source bindings match the executed repository files. See the complete
[protocol](evidence/open_text_frozen_20261030/protocol.json),
[report](evidence/open_text_frozen_20261030/report.json),
[raw completions](evidence/open_text_frozen_20261030/completions.jsonl), and
[external process meter](evidence/open_text_frozen_20261030.process.json).

| Observation | Measured result |
| --- | --- |
| Adaptation | 16 updates; 341,536 trainable parameters; real Hepta content and prefix hashes changed |
| Base LM | 134,515,008 frozen parameters; identical complete before/after parameter hashes |
| Free generation | 12 completions; 544 generated tokens; 49,152-token vocabulary |
| State versus zero state | Different generated text in 3 of 4 cases |
| State versus another source's state | Logits changed, but generated text was identical in all 4 cases |
| Complete fixed-fact checks | State 0/4; zero state 0/4; shuffled state 0/4 |
| Full CLI execution | 74.590 s wall; 140.109 s CPU; 1,788,358,656 bytes peak RSS |
| Local model reuse / new checkpoint | 271,177,292 bytes reused; 3,156,046-byte Hepta/prefix checkpoint |

This closes the executable free-text and gradient path, not source-specific
semantic use or a quality advantage. Failures include describing the mean
documentation without answering the question, inventing `cache_cache_info()`,
confusing file format with mode, and paraphrasing the CSV input instead of its
return value. Narrow predicate partial scores also cannot distinguish every
wrong subject or unsupported claim; they are not general semantic validation.
The blind human review remains pending and no human scores are asserted.

The prior pilot is preserved in `evidence/open_text_20261030`, including its
hash-matched executed-source snapshot and all raw failures. Training, decoding,
scoring rules and data were not tuned from the pilot. The repeat used the final
common checkpoint and added dependency identity metadata. Both executions cost
221.272 s wall and 319.012 s CPU in total. Their different timings are observed
host-run costs, not an algorithmic speedup. The six contract tests pass on the
frozen source.
