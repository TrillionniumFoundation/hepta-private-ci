# NDU six-condition input diagnostic: completed CI evidence

The unchanged VLM call path responds to image and instruction interventions under these short neutral prompts. Semantic reliability is still inadequate: the generated image is called a cat, and the white image is described as a bird. This is diagnostic progress, not a successful image-generation or revision-quality experiment.

## Fixed evidence

- Source: `975e1a264c14ed3da02dcee23a64327825387e42`, PR #4835.
- Completed successful [CI run 41973374316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41973374316).
- Artifact: `13393254163`, 396,825 bytes. The complete downloaded ZIP is retained as `raw-ci.zip`.
- ZIP SHA-256: `d84b6451b4b70e2dcc25b01c72ed5553357c0a9081c96d2f8ebd5248a0cca7aa`, independently matched to GitHub's artifact listing.
- Model: `HuggingFaceTB/SmolVLM2-256M-Video-Instruct`, revision `067788b187b95ebe7b2e040b3e4299e342e5b8fd`; pinned 1,025,998,224-byte weight SHA-256 `dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2`.
- Runtime: Torch 2.8.0 CPU, Transformers 4.57.3, bfloat16, two threads, greedy decoding, a fresh model instance per case. All three runtime source files match the execution plan's byte hashes.

The original photograph, previously generated direct image, white image, all six traces and texts, model acquisition manifests, environment, and source receipt are inside the archive. This review preserves that archive byte for byte. It makes no model or inference-code change.

## Observed outputs

Each image was evaluated under a short caption instruction and a short object instruction. All six calls completed and invoked the actual model once.

| Input | Caption instruction | Object instruction | Output tokens, including EOS |
| --- | --- | --- | --- |
| Original photograph | `a bee on a pink flower` | `bee on pink flower` | 7 / 5 |
| Previous generated image | `A computer screen displays a 3D model of a flower.` | `cat` | 14 / 2 |
| White image | `The text is a simple, straightforward description of the content.` | `A bird flying in the sky` | 13 / 7 |

Direct visual inspection confirms a bee on a pink flower in the original photograph. The generated image contains four round floral patterns and no clear bee or cat. The blank input is white. These are recorded qualitative observations, not an independent benchmark score or a statistical estimate of accuracy. The white-image object response also exceeds the requested five-word limit.

## What the intervention establishes

The independent archive checker recomputes the complete case census, text byte hashes, rendered-template hashes, recorded int64 token hashes, stopping conditions and summary counts:

| Recorded quantity | Distinct values |
| --- | ---: |
| Processed pixel tensors | 3 |
| Vision encoder hidden tensors | 3 |
| Rendered prompts / token sequences | 2 / 2 |
| Decoded output texts | 6 |

For the same image under the two instructions, processed-pixel and vision-output hashes are identical. For the same instruction across the three images, template and token hashes are identical. Nevertheless, the outputs differ for every image within each instruction. This supports actual image sensitivity through the observed call path in these six cases. The raw tensor arrays are not archived; the checker verifies the trace relationships rather than recomputing the encoder numerics.

All six outputs end in EOS token `49279`; none reaches the 80-new-token cap. Each prompt has 91 input tokens. This rules out the new-token cap as the stopping cause in these cases. There is no new diffusion call here, so the earlier diffusion truncation from 115 to 77 tokens is not retested or resolved.

The `local_models.py` Git blob is `48d533d353cdc92c01d69116098344d5d2caaf63` both in this run and in the earlier real execution source `4e3b8c3c242d7d6d83086e7375a354a30647e040`. Thus the result does not rely on quietly repairing the image-binding implementation between those two executions.

## What remains unresolved

The earlier nine identical planning, explanation and critique texts remain negative evidence. This new experiment changes the prompts and uses fresh model instances; it does not cross the exact legacy prompts with fresh/reused instances. It therefore does not isolate whether the old collapse arose from prompt anchoring, the reused execution sequence, model limitations, or another interaction. The six-case result is evidence against an unconditional image-disconnection explanation, not a retrospective proof that every historical image call was bound correctly.

The next useful causal test is a frozen crossing of image, exact legacy versus neutral instruction, and fresh versus reused execution order, preserving template/token/vision/stop traces. No such additional model execution is claimed in this evidence package. No new four-arm training, improved diffusion output, revision benefit, learned-controller benefit, or production qualification has been established.

## Cost and failed attempts

Successful CI diagnosis used 22.041747 CPU seconds and 15.303040 wall seconds, including fresh loads, tracing, cleanup and case writes before the summary write. The six case intervals sum to 20.930003 CPU and 14.189605 wall seconds. Peak process RSS was 2,201,509,888 bytes. These numbers exclude environment installation and model acquisition; they are not directly comparable with the earlier schedules that also ran diffusion.

Two separate desktop reproduction attempts are retained in `failed-desktop/`. The first failed during dependency installation. The retry installed dependencies but failed during model acquisition and never reached diagnosis. Their receipt and acquisition-error records are kept separate from the successful CI run; neither failed attempt supplies semantic output or invalidates the completed CI evidence.

## Reproduce this byte review

From this directory in a checkout of the evidence commit:

```sh
python3 -B verify.py --output /tmp/ndu-input-diagnostic-review.json
```

The standard-library checker reads the pinned ZIP and the unchanged diagnostic source three directories above this file. It does not download models, execute inference or train anything. `ANALYSIS.json` is the successful local result. `VALIDATION.json` records checks actually run and unavailable repository tooling; no full repository CI pass is asserted.
