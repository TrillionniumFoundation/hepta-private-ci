# Restore original CPU evidence

Concatenate the two parts in manifest order to recover CPU_ENGINEERING_01.zip.
Verify its byte count and full SHA256, then verify ZIP CRC and every one of
the 372 file records in EXPORT_INDEX_01.json. That index is the 373rd member.

Ten zero-byte transport lock members remain inside the opaque original ZIP.
They are historical metadata with no evidence or sample meaning; no standalone
lock is added to this repository. Symlink fixtures are explicit metadata,
not links to be followed during restoration.

The archive contains twelve actual behavioral tests and one actual tiny random
Qwen2/PEFT CPU test, including real optimizer and adapter bytes. It contains
zero pretrained Qwen generations, zero real research fits, and zero actual
authored business-verifier executions.
