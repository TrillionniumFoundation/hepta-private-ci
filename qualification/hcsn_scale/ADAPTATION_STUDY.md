# Restricted real-sensor adaptation study

This entry point extends the existing `SequenceModel` and `adapt_model`. It
evaluates one declared editable parameter block on UCI Room Occupancy Estimation
sensor streams. It is not a multimodal foundation-model or knowledge-editing
benchmark. It does not use the occupancy labels for training or selection.

## Fixed protocol

The verified source CSV must have SHA-256
`c090ee5c94b61762bfec9d22767864490b51030f98cca030f02822468db25d9c`.
The existing `real_sensor_data` loader supplies the same chronological windows,
source row IDs, gap handling and actual seconds. Source parsing includes test
rows; this study retains no test tensors and makes **zero test evaluations**.

The earliest 16 train windows form the preservation set. One complete window is
then purged. At most 64 subsequent train windows and 32 dev windows are chosen
by evenly spaced indices, without looking at labels. Windows have 16 sensor
observations. The study reconstructs their raw sensor inputs and fits its
normalizer only on the selected adaptation train inputs. The original loader's
normalizer is discarded. The physical clock scale is the median of the selected
training prediction intervals. Preservation and dev data fit neither quantity.
All source rows, including each window's later query row, are disjoint between
these three sets. Temporal disjointness does not establish IID independence.

Seeds are `181391`, `284729` and `395201`. For each seed all five methods share
one untrained HCSN with the same random predictor, physical continuous-write
law, content feedback and exposure pool as `stream_benchmark.make_model`.
The nearest architecture to the existing 600-parameter target is used and its
actual count and streaming state bytes are recorded. No prior training cost or
knowledge-retention result is implied by this random incumbent.

The editable encoder block is `feedback.projection.weight`. Profile BP and
joint BP each take exactly eight full-data Adam steps at learning rate 0.001.
Profile BP conditionally solves the predictor and differentiates the profiled
objective; joint BP trains the predictor alongside that encoder block. Direct
only solves the predictor; KEEP changes nothing. This comparison is restricted
to that block. The separate stream study covers full-encoder BP.

Bounded editing proposes eight fixed deltas: positive/negative drift, reward,
same-sign drift-plus-reward, and opposite-sign drift/reward directions. Each
delta has L2 norm 0.02 and is applied to the common incumbent, independently of
all other candidates. Its within-row direction is uniform over marked-content
coordinates. The boundary-feedback row remains zero. BP can update all three
rows of the same declared matrix, so its actual direction space is broader.
These are declared coefficient interventions, not an LLM-generated WSP search,
and their sign does not guarantee a beneficial change on every signed state.

Every updating arm explicitly pays for its conditional readout when applicable:
one centered SVD per current design and all 15 sensor target columns as right
hand sides. Positive ridge is 0.001; the intercept is unpenalized. No encoder
features or decomposition survive a parameter or split change. The encoder
edit norm does not bound the separately solved predictor change.

Candidates require dev MSE improvement of more than `1e-12` and preservation MSE
no more than the incumbent plus 0.01. These are next-sensor MSE rules on the
supplied windows; they are not guarantees about other tasks, occupancy accuracy
or retained knowledge. Every rejection remains recorded. If none is admitted,
the result is KEEP. There is no selection across arms using test performance.

## Running and artifacts

Use the verified CPU FP64 Torch environment from the repository overlay root:

```sh
python -m unittest qualification.hcsn_scale.adaptation_study_tests
python -m qualification.hcsn_scale.adaptation_study source.csv output_directory
```

The default runs all 15 trials serially. A single declared trial can instead use
`--arm profile_bp --seed 181391`; the manifest reports that it is only one of the
15 planned trials. Output directories must not already exist. This entry point
has no resume mode: failed/interrupted attempts remain separate charged runs.

`PLAN.json` and `STUDY.json` bind the fixed plan, source code hashes, exact window
IDs, normalization, runtime and measured shared costs. `prepared_inputs.npz`
stores the actual sensor tensors, dt and IDs used. Each seed saves its common
incumbent, every declared delta and the edit manifest. Each arm saves
`RESULT.json` and `candidates.pt`: all evaluated candidate states keyed by digest,
the selected state and the complete selection/cost ledger.

Costs include forward calls, sensor-transition rows, backward evaluations,
conditional solves, right-hand sides, factorizations, all dev/preservation
queries, initialization, serialization and complete study wall/CPU time.
Selection time includes its feature evaluation time; phase times overlap and
must not be summed. Module-entry time includes imports after the entry clock;
OS/Python launch overhead is outside that clock and can be measured externally.
All shared preparation and initialization costs are charged once, not dropped.
Failures retain their measured external elapsed time; unfinished internal work
is marked unknown rather than zero. Only completed runs promise complete
candidate snapshots. The intended conclusions concern this measured restricted
problem, not general training-time superiority or replacement of encoder BP.
