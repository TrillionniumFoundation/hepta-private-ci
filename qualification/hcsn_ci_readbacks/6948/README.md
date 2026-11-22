# #6948 authentic compact checkpoint readback

This directory preserves the exact 17,089,235-byte artifact ZIP from the sole
admitted #6948 run as 35 ordered Git parts, plus exact extracted `RESULT.json`
and `RUN.jsonl` bytes.

The independent verifier reconstructs the artifact, verifies its SHA-256 and
CRC, reconstructs the immutable #6944 raw-input ZIP, parses every compact
header without importing the candidate serializer, performs bounded XZ decode,
and requires all ten restored full-state byte strings to equal their #6944
canonical originals directly. Normal and `python -O` verification each perform
ten XZ decodes and zero recurrence, tail, provider, dynamic, exponential,
Torch, optimizer, model, or training operations.

This evidence closes only the index256 lossless compact serialization and its
measured storage/cost record. It does not execute index537 or qualify N256.
Historical RED/UNKNOWN, C2 full replay 0/6, HPCA external custody, equal-budget
benefit, asynchronous cost, and production adoption remain open. Global status
is HOLD / `all_closed=false`.
