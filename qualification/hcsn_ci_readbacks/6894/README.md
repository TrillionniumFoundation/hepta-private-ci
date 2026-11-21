# N256 runtime identity admission originals

This evidence-only readback preserves all three same-key attempts from Draft #6894.

- attempt 1: run 44910798387 / job 136865986747 — RED during receipt publication; 0 candidate execution
- attempt 2: run 44910947077 / job 136866426687 — RED during receipt publication; 0 candidate execution
- attempt 3: run 44911092060 / job 136866866262 — workflow success, explicit admission rejection; 0 candidate execution

The terminal artifact is 1,197 bytes with SHA-256 `055bd4b6551f2d0524e5a938faea9398d8b77c79ecdbb5509a1ff059029fa7a8`. It records `admitted=false` because NumPy and SciPy RECORD-file hashes differ from the oracle, even though Python 3.12.3, the Python executable, platform, package versions, both package `__init__.py` hashes, machine, and thread environment match exactly.

The guard imported no numerical module and executed 0 model, dynamic step, expm, Torch call, or optimizer step. This closes only the fail-closed runtime admission control. The #6890 665/69728 RED and all OOM/cancelled/UNKNOWN records remain. N256 numerical qualification, C2 full replay (0/6), HPCA update, production adoption, and global closure remain open/HOLD.
