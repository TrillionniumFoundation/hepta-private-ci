# Development results

These results are development history, not scientific qualification or external custody.

## RED 001 — candidate REQUEST identity/classification

- Normal Python unit suite: 5 tests, 3 passed, 1 failed, 1 errored.
- Cause: the publisher request carried an incorrect candidate `REQUEST.json` SHA-256 and the verifier incorrectly treated that binding-only SHA as a field that must already exist in the parent oracle request.
- Reached before: publisher output, provider admission, external reviewer custody, oracle execution, dynamic execution or optimization.
- Counts: 0 external originals, 0 published bindings, 0 provider/oracle/serializer calls, 0 dynamic runs, 0 optimizer steps.
- Repair: bind the candidate request to its actual immutable SHA-256 and distinguish parent-request-bound source identities from the additional identity emitted into the future binding.

## RED 002 — direct verifier entry point

- Normal and optimized unit suites: 5/5 passed in each mode.
- Direct `verify_source.py` entry point: failed with `ModuleNotFoundError: qualification`.
- Reached before: publisher output, provider admission, external reviewer custody, oracle execution, dynamic execution or optimization.
- Counts: 0 external originals, 0 published bindings, 0 provider/oracle/serializer calls, 0 dynamic runs, 0 optimizer steps.
- Repair: add the repository root to `sys.path` before importing the frozen package, matching the workflow's direct-script invocation.

## Local source-only result after repairs

- Normal Python unit suite: 5/5 passed.
- Optimized `python -O` unit suite: 5/5 passed.
- Static inspector: `PASS_ORACLE_BINDING_PUBLISHER_SOURCE_HOLD`.
- Exact parent-source verifier: `PASS_N256_ORACLE_BINDING_PUBLISHER_SOURCE_HOLD`.
- `compileall` and `git diff --check`: passed.
- Executed work: 0 external originals, 0 published bindings, 0 provider/oracle/serializer calls, 0 dynamic runs, 0 matrix-exponential actions, 0 Torch calls and 0 optimizer steps.

Status remains `PASS_SOURCE_ONLY_HOLD_EXTERNAL_ORIGINALS / HOLD / all_closed=false`.
