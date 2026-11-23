# Cross-production piano and guitar recordings

This workload asks which of two instruments a new recording contains. Wikimedia Commons is the distribution platform for 22 individually attributed works from 21 independent production groups. One dedicated gallery work of each instrument provides the class references. No performer, production group, file checksum, uploader or gallery recording crosses a split. St Cecilia’s Hall supplied one square-piano and one guitar recording to DEV. Distinct musical works, rooms, instruments, microphones, cameras, editing choices and musical genres remain uncontrolled. Four excerpts per recording share those properties.

| Split | Piano works | Guitar works | Excerpts |
|---|---:|---:|---:|
| Gallery | 1 | 1 | 8 |
| Train | 3 | 3 | 24 |
| Dev | 2 | 2 | 16 |
| Retain | 2 | 2 | 16 |
| Test | 3 | 3 | 24 |

The original published recording of a physical piano or guitar must include a video and an audio track. Piano includes a historical player piano and a miked Steinway with effects. The live amplified-guitar examples can include backing instruments. The target is the primary documented instrument. The written musical score overlaying a keyboard-camera view is present in one original. All source titles, author credits, file-description revision links, licenses, source upload timestamps, original hashes and group decisions appear in `sources.json`. Source curation used published descriptions, stream metadata and visual inspection of available media. The synthesized Schubert, the violin-plus-piano recital and a mixed WikiOrchestra arrangement were excluded before scoring. Publisher labels describe the production. The continuous soundtrack can contain rests, applause or other sounds in individual windows. No noise, synthetic corruption, paired waveform copies or required frame labels are added. The licensing of each original is listed individually in the manifest. This package supplies metadata and acquisition/analysis code. Media are downloaded from the original file publisher.

The segment rule retains four linearly spaced 2.88-s excerpts per recording inside the central 90% when at least four excerpts and their gaps fit. Every excerpt has six successive 0.48-s decision intervals. Each split-specific roster records the exact absolute start offset, immutable recording identifier and producer grouping. Audio is free at each prefix. Incremental visual observations are logically withheld by the downstream action policy. Offline feature extraction may decode all frames; the policy’s READ price measures a decision cost and does not time an online video service.

## Reproduce the descriptors

From a checkout containing the qualification package, install NumPy and make FFmpeg and FFprobe available. To populate a local cache and verify checksums, run:

```sh
python qualification/hcsn_intervention_value/media/acquire.py --root /path/to/commons
python qualification/hcsn_intervention_value/media/verify_media.py
```

The acquisition command verifies each original against the frozen byte length and publisher-supplied SHA-1, logs SHA-256 and records throttling or retries. Run one builder per required split:

```sh
python qualification/hcsn_intervention_value/media/build.py --root /path/to/commons --split gallery
python qualification/hcsn_intervention_value/media/build.py --root /path/to/commons --split train
python qualification/hcsn_intervention_value/media/build.py --root /path/to/commons --split dev
python qualification/hcsn_intervention_value/media/build.py --root /path/to/commons --split retain
python qualification/hcsn_intervention_value/media/verify_media.py --root /path/to/commons
```

A separate process can materialize and inspect the sealed TEST descriptors with `--split test`. Fit processes have no reason to open this shard. The per-split NPZ stores `audio` and `visual` as float64 arrays shaped `(excerpts,6,52)` and `(excerpts,6,76)`. The last two axes index time and features. They are cumulative arithmetic means of the prefix's interval descriptors. `audio_block` and `visual_block` store the underlying six interval vectors. `dt`, `label`, `group`, `recording`, `query_id`, `start_seconds` and `split` provide clocks and provenance. Piano is label 0 and guitar is label 1. The independent fixed gallery has the same fields. The gallery and query features are computed from distinct source files.

The acoustic frontend uses 24 logarithmically spaced frequency bands, their normalized energy profiles and four level, centroid, zero-crossing and spectral-change statistics. The visual frontend uses 48 regional color means, 16 spatial gradient magnitudes, 8 regional motion measures, three color-channel deviations and one grayscale deviation. Each interval averages twelve 40-ms observations. Video selects the last presented frame before the observation deadline and performs no temporal interpolation. No target, recording identity, source identifier, time after the deadline or gallery sample enters either descriptor.

## Original source-clock coverage

A post-seal, full linear decode of all original PCM frame timestamps found that 22 of the 24 registered TEST excerpts cover their full intervals. The original media lack the first 412 samples of the scheduled Yerevan bookstore excerpt `commons-112833470-w01` and the last 7,666 samples of `commons-31045040-w04`, both at 44,100 Hz. The latter has five fully observed prefixes. Their recording identities and scheduled intervals stay in the original roster and the eligibility receipt. The complete-case TEST archive has 11 guitar and 11 piano excerpts from all six registered TEST producers. The first five prefixes of the partial guitar query have a separate archive. A same-recording control reproduced all four arrays of the corresponding prefixes bit-for-bit.

To recheck from the frozen 24-episode roster:

```sh
python qualification/hcsn_intervention_value/media/build.py --root /path/to/commons --split test --roster-only
python qualification/hcsn_intervention_value/media/coverage.py --roster /path/to/commons/roster/test.json --out /path/to/commons/test_audio_coverage.json
python qualification/hcsn_intervention_value/media/complete_cases.py --root /path/to/commons --split test --coverage /path/to/commons/test_audio_coverage.json
python qualification/hcsn_intervention_value/media/valid_tail.py --root /path/to/commons
```

Some original codecs exhibit offsets in PCM presentation timestamps that cancel later in the recording. A strict window has full endpoint coverage and no internal gap or overlap larger than one source timestamp tick. Gallery, TRAIN, DEV, RETAIN and TEST contain respectively 4/8, 15/24, 16/16, 5/16 and 22/24 strict windows. The largest clock excursion within non-TEST windows was 10.16 ms in gallery and TRAIN and 19.34 ms in RETAIN. Changing the timing definition changes which windows qualify. The evidence archive includes per-source and per-window clock measurements. Reproduce the fixed-score sensitivity with:

```sh
python qualification/hcsn_intervention_value/media/clock_sensitivity.py --raw /path/to/commons --discovery /path/to/frozen/discovery --output /path/to/clock_sensitivity.json
```
