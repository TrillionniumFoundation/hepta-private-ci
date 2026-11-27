# Decoder-bound finite-code codec reuse hypothesis

This is a prospective implementation candidate, not a measured repair or a qualification result. It uses the retained TRAIN breakdown and source, without reading formal results or held-out inputs.

Across 216 TRAIN calibration requests per seed, output encoding plus its ledger consumed:

| Seed | Service CPU (ms) | Generation+ledger (ms) | Output+ledger (ms) | Output fraction |
|---|---:|---:|---:|---:|
| 11 | 162.171136 | 37.425399 | 124.376073 | 76.69% |
| 23 | 18.222238 | 2.798681 | 15.305252 | 83.99% |
| 47 | 51.214770 | 8.887626 | 42.162215 | 82.32% |

The expensive seed 11 repeat medians are 809584.3125, 763512.875 and 476919.484375 ns/request. All three are retained; this is not one removable outlier. Every request executes the same 19236 declared units, and same-seed output-byte arrays are identical across repeats. The timing variation's cause remains unknown.

`independent/evaluation.py::_outputs` decodes sampled image codes, quantizes them and calls PNG encoding per request. `FrozenGenerator` owns a read-only decoder with 12 fixed image-code rows. A sampled code's learned image and PNG are thus deterministic for that decoder, independently of input labels. The source supports a local per-generator 12-code codec table as concrete repeated-work reuse.

A valid implementation must bind the table to that generator's exact decoder snapshot and quantization/codec specification; produce all 12 images/PNGs during actual charged preparation; retain each request's original categorical RNG order, caption/choice selection, JSON construction and actual serialized output; preserve byte-identical PNG, SHA256 and base64 results; and keep corrupted-decoder observers independent. A table must never be shared by changed decoders or cache ground-truth outcomes, inputs or scoring results.

All actual table preparation, decoding, codec work, memory and lookups must remain in complete CPU accounting. Arithmetic inventories must quote only decoder operations actually executed; no per-request decoder charge remains if it was replaced by an already-paid lookup. PNG/JSON primitives retain byte and measured CPU accounting rather than invented FLOPs. Every arm needs the same service implementation. Existing uncached protocols and failures must remain retained; this changes the declared codec profile prospectively.

The component timer combines sampling, learned decoding, quantization, PNG/hash/base64, JSON and output-ledger work. Its 76.69–83.99% share is an upper bound on the affected segment, not a measured PNG-only cost or a promised speedup. There is no evidence here that caching explains the execution-wave variability, improves content or makes either independent contribution statistically reliable.

The supported next step is implementation plus hand-array equivalence and accounting tests for a separately declared codec profile. No new timing measurement, training, data construction or confirmation is proposed or performed by this assessment. Whether any actual saving can fund content updates, and whether those updates generalize, remain separate questions.
