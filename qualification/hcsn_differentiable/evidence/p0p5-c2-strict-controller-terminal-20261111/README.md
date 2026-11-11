# Successor C2 terminal JSON strict admission — isolated r12

This candidate was forked from exact 3cad9347f5729ce19937202347467095fda36357 without changing the original desktop C2 run or other working trees.

## Counterexample and fix

terminal_result_gate() formerly checked the terminal result.json byte identity but parsed with permissive json.loads. Real native RED tests demonstrated accepted terminal evidence with duplicated top-level status, duplicated nested model_configuration, duplicated parent-report keys, NaN, and a 1e999 float silently decoded as infinity. The byte hash still matched the deliberately constructed inputs. This is **not** evidence that the original four producer reports were malicious.

The fix adds one bounded strict JSON object decoder, rejects duplicate keys at every depth, JSON non-finite constants and floats with overflow, limits raw bytes to 16 MiB, and applies the same parser at five actual controller decision inputs (terminal result, original parent report, execution contract, runtime identity report, original campaign roster). The code still makes no scientific promotion.

- Environment preflight (system Python without Torch): 1 import error, exit 1; retained.
- Actual exact runner RED: 7 tests, 5 failed assertions, exit 1.
- Targeted native GREEN: 7/7, exit 0.
- Combined successor native GREEN: 39/39, exit 0.
- Python 3.12.14 and Torch 2.8.0+cpu, desktop; distinct from older desktop Python 3.12.3 + CUDA and GitHub's Python 3.12.3 CPU.
- SHA-256 for all raw logs, Git blob hashes of the code and test, and the exact parent source appear in EVIDENCE.json.

This validates a controller parser sub-boundary only. The original C2 1a1c74f3308-be2a-75 remains unknown terminal, 4/6 producer result.json, two zero-byte interrupted.pt, 0/6 independent full training replay. No original checkpoint/model was loaded, no execution decision was granted, no HCSN C2 training was started. P0–P5 remain HOLD_NO_GO. Hosted CI must be checked for the new exact head before claiming its fixture pass.
