# Continuous spiking network data contract

## Scope and interpretation

The suite has an independent synthetic mechanism task and real public image/audio
encoder tasks. None is evidence of general multimodal foundation-model scaling.
`multimodal_select` is the primary combined task: an independently chosen MNIST
image and FSDD recording may have different digit classes, and a four-token query
asks for the image or spoken digit. `multimodal` pairs sources by class instead.
Neither pairing is a naturally synchronized audio-visual event. The query is a
small fixed instruction vocabulary, not a natural-language understanding benchmark.
It never includes the answer digit or a digit-word embedding.

`mnist` and `fsdd` remain independent single-modality evaluation tasks. A combined
score alone can hide a weak audio encoder behind image recognition. Report them
separately and use modality masking on the combined task.

## Sources, attribution and licenses

| Source | Attribution | Pinned identity | License |
|---|---|---|---|
| MNIST | Yann LeCun, Corinna Cortes, Christopher J.C. Burges | Four canonical IDX gzip files, upstream MD5 verified | CC BY-SA 3.0, as documented by Keras |
| Free Spoken Digit Dataset | Zohar Jackson and FSDD contributors | `26eb9aaf76e81b692f806f9140c2d2777410d7a1` | CC BY-SA 4.0, upstream README |

Source and license references:

- MNIST: <http://yann.lecun.com/exdb/mnist/>;
  <https://keras.io/api/datasets/mnist/>.
- The MNIST mirror and canonical checksums are also used by torchvision:
  <https://github.com/pytorch/vision/blob/main/torchvision/datasets/mnist.py>.
- FSDD: <https://github.com/Jakobovski/free-spoken-digit-dataset/tree/26eb9aaf76e81b692f806f9140c2d2777410d7a1>.
- FSDD license: <https://github.com/Jakobovski/free-spoken-digit-dataset/blob/26eb9aaf76e81b692f806f9140c2d2777410d7a1/README.md#license>.

The downloader writes archive SHA-256, all four MNIST SHA-256 values, every FSDD
recording SHA-256 and the feature-cache SHA-256 to `sources_manifest.json` outside
the repository. It preserves the upstream FSDD README beside the recordings.
Do not commit raw audio, images, derived feature arrays, or download archives.
Licenses and attributions apply to any redistributed derivatives.

Verified download SHA-256 values:

| File | SHA-256 |
|---|---|
| MNIST train images | `440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609` |
| MNIST train labels | `3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c` |
| MNIST test images | `8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6` |
| MNIST test labels | `f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6` |
| Pinned FSDD ZIP | `beaca4fb849cad13103b2cffba913b3d7fdb5f15222da4ddd07187b3c38a757a` |

The loader checks source/feature hashes against an available manifest before
returning real data. Missing manifests are explicitly marked as unmanifested;
unit-test fixtures use that path. Research results must carry a source manifest.

## Split independence

MNIST retains the official 60,000 training / 10,000 test source partition.
Validation images are held out from the official training sources using a fixed
class-stratified partition independent of model seed and requested training size.
No image source is shared across train, validation and test. Writer IDs are not
provided by this IDX source; no writer-independent claim is made.

FSDD uses a custom speaker-disjoint split, deliberately different from its upstream
recording-index split:

| Split | Speakers | Available independent recordings |
|---|---|---:|
| Train | george, jackson, nicolas | 1,500 |
| Validation | theo | 500 |
| Test | lucas, yweweler | 1,000 |

When requested episodes exceed unique recordings, audio sources cycle within their
own split. For example, 4,096 combined training episodes contain 4,096 independent
images but at most 1,500 independent recordings. Every result must distinguish
episode count from unique image/recording count. Only two test speakers are
available; recording-level confidence intervals do not establish population-level
speaker-generalization significance. `group_ids` are speaker IDs for audio tasks.

## Representation and time

`SplitData` exposes `x: float32[N,T,64]`, `dt: float32[N,T]`, `y: int64[N]`,
`group_ids`, `sample_ids`, and source metadata. `DataBundle` contains `train`, `val`,
`test`, feature/class names, and a provenance manifest. No preprocessing statistics
are fitted on any split. Images use 28 rows of 28 pixels scaled by 255. Audio uses
fixed 20-band log-mel features from PCM16 mono 8 kHz, resampled to 28 frames. Audio
resampling uses the complete utterance duration; these are offline encoders, not a
claim of native causal audio streaming. Image row-scan time is also artificial.

For the real encoder tasks, the canonical sequence has 28 sensor steps followed by four query tokens. Lengths
32, 64 and 128 contain exactly the same evidence at exactly the same cumulative
times. Longer contexts subdivide `dt` and insert all-zero no-evidence steps; they
do not create fresh observations or independently resampled noise. Total duration
is 32 model-time units. All models receive the same elapsed times. Report these as
sampling-density/idle-step experiments, not an increase in independent context
information or native audio duration. Model training should shuffle episodes.

The synthetic task presents seven noisy observations for each of four random
key/value associations across two distinct sensor channels. A final query gives
only a key, and the target is its value. Quality is observed, noise is independent,
and later queries are absent from earlier inputs. The task is causal keyed evidence
retrieval. Independent per-episode RNG streams keep training prefixes and held-out
sets stable as sample counts change. The feature slots used for keys/values are
synthetic encodings and are not actual image/audio measurements.

## Genuine history growth: `long_memory`

This separate synthetic task is the main context-length axis. The first four
observations write a random bijection from keys 0–3 to values 0–3. Every following
observation before the query carries a new independent value for a distractor key
in 4–7; these keys never repeat an initial target association. The last observation
queries one of keys 0–3 without including its value. Both channels encode values,
and the initial key order and channel are randomized. All four value classes occur
once initially, so their overall histogram cannot answer a key-specific query.

At T=32/64/128 there are respectively 27/59/123 genuine distractor observations.
No blank padding or repeated target evidence is added. Independent RNG streams
separate initial associations, query choice, distractors and timing. For the same
episode seed, the four associations, query key and shared distractor prefix are
identical across lengths; only the query is delayed. Positive irregular increments
have expected dt=1, so physical history duration grows with T. Retaining a fixed
number of useful associations amid more interference is being measured, not an
increase in the number of target associations or unrestricted natural long-context
reasoning. Its input remains [N,T,64], with a four-class target and stable source IDs.

Tests reconstruct every answer from only the initial associations plus the query,
verify that intervening observations use only disjoint keys, check obvious
query-only/distractor-only proxies against chance, and verify identical source
prefixes with genuinely increasing observation count and elapsed time. Statistical
proxy checks supplement the independent generation contract; they are not a proof
against every possible leakage detector.

## Reproduce

```bash
python -m experiments.continuous_spiking_network.prepare_data --cache-dir /path/outside/repo/hcsn-data
python -m unittest experiments.continuous_spiking_network.tests.test_data
```

```python
from experiments.continuous_spiking_network.data import load_data
bundle = load_data("multimodal_select", train_size=4096, val_size=500,
                   test_size=1000, context_length=64, seed=0,
                   cache_dir="/path/outside/repo/hcsn-data")
```

`load_data` does not download. Source and speaker overlaps are checked before a
bundle is returned. Query-content, stable-prefix, source-disjointness and physical
time preservation are covered by tests. Inspect `manifest["source_counts"]` when
comparing training-set scaling, and retain the exact source manifest with results.
