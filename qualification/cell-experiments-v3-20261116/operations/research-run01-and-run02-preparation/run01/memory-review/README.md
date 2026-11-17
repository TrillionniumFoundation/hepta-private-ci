# Research 01: memory-gate failure review

All six primary workers failed their first explicit available-memory check before Qwen was loaded in that worker. The seven real worker LAUNCH/EXIT pairs are strictly sequential. Collection exited 0; all six primaries exited 1, without timeout. The coordinator's owned wait returned 0 because it preserved and reported a partial study.

## Actual execution order

| Worker | PID | Exit | Gap after previous EXIT (ns) |
| --- | ---: | ---: | ---: |
| corrections-collect | 2230050 | 0 | n/a |
| parent-primary | 2249477 | 1 | 179689325 |
| retrieval-primary | 2251612 | 1 | 181444323 |
| final_answer-primary | 2252274 | 1 | 218255651 |
| trajectory-primary | 2257813 | 1 | 192363773 |
| shadow_correction-primary | 2262730 | 1 | 181485589 |
| controlled_correction-primary | 2266379 | 1 | 176774124 |

Exact integer timestamps, original file hashes, worker traces, and receipt seals are retained in REVIEW.json and ORIGINAL_INDEX.json. Original byte copies are under originals/. All 31 selected Desktop files were reread and verified unchanged after collection.

## Gate and allocation order

- parent/retrieval: research_sft_execution_v1.py line 129 calls check_device after gc.collect/empty_cache, before load_predictor at line 132.
- Four fits: research_sft_train_v1.py line 135 calls check_device after six authored-reference rechecks, before memory-fraction setup, Predictor at line 142, LoRA, optimizer, and fit_steps.
- causal_probe_v3.py lines 309-311 read mem_get_info and reject free bytes below 4294967296. The failing branch does not save the actual free-byte value.
- Predictor has its own pre-load check at line 331, before model .to(device). None of these six traces reaches its constructor.
- The collection Predictor close drops model/tokenizer references and collects Python garbage, without explicit empty_cache. Its process actually exited before parent-primary was launched. No live owned-worker overlap appears in the retained receipts. CUDA-context overhead and driver-reclamation timing were not instrumented.

This establishes failure before this worker's Qwen/LoRA/optimizer allocation. It does not establish zero CUDA overhead in the process or exclusive attribution to another process.

## Memory observations and limits

The first actual shadow output records 5799280640 B (5530.625 MiB) available before collection model load. The unchanged threshold is 4 GiB. Root separately observed 6531 MiB before the operation and 3963 MiB later, including a different PID 2228309 using 2570 MiB; that source is linked by SHA in ROOT_INSPECTION_REFERENCE.json and is not a measurement at each failed check.

In this review's one bounded read-only identity observation, PID 2228309 was already absent. No PPID or script ownership was established, no environment or inline -c code was retained, and no signal was sent. Its ownership and exact causal contribution remain unknown.

## Scientific and accounting boundary

The actual retained collection has 6 shadow outputs, 1727 input tokens and 1764 output tokens. The coordinator ledger retains 36 authored-reference receipts. There are 4 training-entry STARTED records, 0 completed fits and 0 completed step receipts. The raw partial ledger's overall training-step total remains null, not rewritten to zero; the failure callsites independently show these four fits did not reach an optimizer update. Unknown total costs remain unknown; nested process costs are not added again.

These are failed execution and descriptive engineering records. They add no independent sample, teacher, user, new C, Cell adoption, Circuit, PoUW or capability evidence. A separately numbered resource reschedule must preserve this operation and its costs and cannot be described as a preregistered first run or new sample.

## Package

The ZIP is a selected review bundle, not the full study archive. MANIFEST.json lists every bundled member and SHA. REVIEW_VERIFIED.json binds ZIP SHA, CRC/member hashes, and unchanged copied source bytes. TRANSFER.json and RECHECK_TRANSFER.json are local transfer containers and are excluded from the ZIP to avoid duplicate evidence bytes. No model or reference was executed and no frozen source was changed by this review.
