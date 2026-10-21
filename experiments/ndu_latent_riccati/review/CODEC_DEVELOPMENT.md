# Codec capability development and retained failures

These are development-only capability checks. The decoder is supplied with the
true six factual coordinates and a lawful style coordinate, so the check is an
upper-bound diagnostic for the codec, not an inference policy or NDU efficacy
result. All checks use 128 development validation worlds from seed `4000919`.
The official heldout model-comparison worlds were not accessed during this work.

## Why the initial experiment was not admissible

The original 128-wide shared MLP emitted all four raw modalities through linear
heads. After 600 updates, even correct latent coordinates produced no fully
correct, resolved outputs. After 6,000 updates, text and audio became accurate,
but small positive background errors in image/video outputs inflated spatial
width. Passing such a codec to the model comparison would have tested an output
decoder failure rather than the intended control mechanism.

ReLU intensity outputs reduced background errors but introduced dead foreground
pixels. After the subsequent moment-loss development run, 9,097 of 13,331 true
foreground pixels above 0.01 had negative preactivations and zero ReLU gradient.
The retained result remained a failure. Replacing ReLU with a squared intensity
link removed that support problem without changing the evaluator.

The fresh squared-output run then localized every factual failure to video
velocity: among 128 worlds, 33 exceeded the fixed velocity-x error tolerance and
24 exceeded the velocity-y tolerance, for 41 distinct failing worlds. All text,
audio, and image factual coordinates were inside the same tolerance. Video
width accounted for 36 style failures, compared with six image-width failures
and zero audio-phase failures. This motivated sharing a learned frame decoder
across physical times rather than increasing every model component.

## Retained development outcomes

| Development attempt | Updates / initialization | Raw factual loss | Correct and resolved | Resolved | Lawful and consistent style |
| --- | --- | ---: | ---: | ---: | ---: |
| Linear raw heads | 600, fresh | 0.642266 | 0% | 0% | 0% |
| Linear raw heads | 6,000 total | 0.500245 | 0% | 0% | 0% |
| ReLU intensities | 2,000 more from linear 6,000 | 0.066685 | 37.50% | 82.03% | 3.91% |
| ReLU plus moment loss | 4,000 more from ReLU attempt | 0.407138 | 1.56% | 3.13% | 3.13% |
| Squared intensities plus moments | 4,000 from linear 6,000 | 0.001383 | 75.00% | 100% | 75.78% |
| Squared intensities, separate video head | 10,000 fresh, cosine learning rate | 0.001664 | 67.97% | 100% | 71.88% |
| Shared time-conditioned frame decoder | 10,000 fresh, cosine learning rate | 0.000367 | **99.22%** | **100%** | **99.22%** |

The final development codec passed the previously selected admission conditions:
at least 80% correct-and-resolved, 90% resolved, and 80% lawful-and-consistent.
The five official training seeds must still pass their own frozen pre-heldout
codec admission checks. No scientific superiority conclusion follows from the
development codec passing.

## Final declared architecture and physical prior

The decoder has **225,442 trainable parameters**. Text, audio, and the text-order
style head use the original 128-wide neural path. Images and videos use one
learned frame MLP, `8 -> 192 -> 192 -> 768`, taking the seven-dimensional state
and physical frame time. Time zero produces the image; times `-1, -1/3, 1/3, 1`
produce the video frames. Physical frame time is separate from generation time.
No analytic motion formula or Gaussian renderer is called by this decoder.

Image and video intensities are the square of raw neural outputs. Training sees
exactly these emitted nonnegative tensors. The training loss is the balanced
four-modality raw loss plus 0.15 times style cross-entropy and 0.5 times the mean
image/video moment loss. Moment loss compares relative RGB channel mass,
centroid in fixed 0.24 position units, and RMS spatial spread in fixed 0.08 units,
all computed from raw training targets. This is an explicit task-specific
physical training prior; it is not a universal semantic representation theorem.

The successful fresh run used initialization seed 919, minibatch generator seed
950, 2,048 training worlds, batch size 64, and 10,000 AdamW updates with cosine
learning rate from 0.001 to 0.0001. Runtime was 94.58 seconds in the observed CPU
preflight environment. No validation-dependent early stopping was used. The
semantic, resolution, and style thresholds remained unchanged across the codec
repair attempts in the table.

The modality interfaces remain structured numeric text, short synthetic
sinusoids, RGB blobs, and four-frame motion videos. Audio frequency is specified
in cycles per 64-sample window, not a claimed natural-speech or Hertz benchmark.
The final common codec is frozen for every controller comparison within a seed.

## Evidence locations

Development artifacts are retained under `ndu-latent-evidence/`:
`development-01`, `development-02`, and `codec-development`. The successful
decoder-only checkpoint and receipt are named `decoder-frame192-10000.pt` and
`decoder-frame192-10000.json`. Earlier checkpoints and receipts retain their
original names and results. The successful codec source SHA-256 is
`d870e9e201547136efed138a4cd3d811e28567c07af30a39eea0496818d20362`.
