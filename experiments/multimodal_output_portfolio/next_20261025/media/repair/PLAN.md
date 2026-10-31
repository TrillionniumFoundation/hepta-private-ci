# Frozen development repair scope

The retained V2 development failure has two identifiable causes. Four of twelve audio-input tasks are already classified incorrectly before physical codec serialization, as verified against prior predictions for the exact same recording SHA. In the image-input route, image/text/audio semantics are correct on eleven of twelve tasks, while the strict all-frame video score is correct on eight. A fixed ASR ensemble recomputation does not remove either of these errors.

## Training and selection budget

Train exactly two additional `MelSpeech` ingress members, seeds 23179 and 23197, for 2,000 steps each, on the existing 3,000 official-training recordings. The optimizer, 32-example batch, masking, and .0008 cosine learning-rate recipe match the completed first ingress fit. No old validation/development recording or fresh qualification recording enters a gradient. Neither output audit model nor ASR is loaded by this training entry point.

The four declared candidates are the original member, the two new individual members, and their equal probability mean. Evaluate all four on the previously used 300 validation recordings and the exact same twelve development audio-input tasks. These are development criteria, not independent qualification. Prefer candidates passing both 255/300 recording accuracy and 9/12 audio-pair accuracy, then maximize recording accuracy, then pair accuracy, then the declared candidate order. If no candidate passes, retain the best candidate and the failure; the new qualification gate remains closed.

## Finite semantic commitment

For every input route, obtain the predicted digit posterior without ground truth. Make a hard semantic commitment from that posterior, reconstruct a canonical shared state with the existing learned generator, and run its existing refine-semantic/couple transitions. The actual text, image, neural waveform, and recurrent motion heads all decode that committed state.

This condition produces canonical finite-class outputs. It does not preserve the input handwriting style and makes no claim of natural-video fidelity. It changes the generation condition, not the original numeric acceptance thresholds. It is separate from the parent's matched mean-versus-entropic training experiment; those six trained models are not replaced by this repair.

## Actual media and observer caching

The repaired candidate still generates all physical UTF-8/PNG/WAV/MP4 outputs and reopens their actual codec bytes. The student waveform weights are unchanged, so its ten deterministic hard semantic conditions can reuse independently measured ASR observations of exactly identical PCM events. `MEASURED_EVENT_CACHE.json` contains only target-free observations, actual event hashes and original waveform paths, with provenance hashes. Silence is the eleventh measured event. Unknown PCM bytes fail closed; there is no label-based fallback.

The cache validates both original measured files and the actual component ASR asset identities. It preserves ordered physical event boundaries. This saves repeated model execution without claiming new ASR inference. Original cold ASR process costs and per-event costs are retained; warm lookup and physical regeneration costs are measured separately.

## Independent qualification before confirmation

Only after the repaired candidate passes all original development sample gates will `freeze_qualification.py` pin the selected classifier, generation source, complete development receipts, and the previously fixed V3.1 observer. The same fresh 300 recordings from 147 untouched official-test speakers then separately qualify the frozen input classifier and the frozen ASR ensemble at the unchanged 85% point threshold. All model and rule choices precede those outcomes. The component ASR/parser/transform code remains byte-identical to the earlier V3.1 selection.

The ASR qualification executes actual models, not the finite output-event cache. The parent's joint experiment can use that qualified live observer for its changed waveforms. The reserved 128 media image pairs / 32 writer-speaker clusters remain inaccessible until the development, independent ingress and independent ASR gates all pass. Final confirmation fixes all parameters, source identities, rules and thresholds and retains every outcome.
