# Native attempt 1: runtime identity gate

Source: `55df4b4fe380fbdfe85ba70a56fe56c25aa2e63b`.
Host: `ai395`; durable job: `1a1cd3731c3-2564-121c`.
Idempotency key: `hpca-base-output-e901-execute-55df4b4-20261112-v1`.

The five contract tests passed (0.003 seconds). The diagnostic then exited 1
at the runtime identity gate. Downloads, their required identity checks and
runtime imports precede this gate; tokenizer/model loading, PREEXECUTION and
all model inference follow it. Completed model inference attempts: **0**.
The raw worker status is retained verbatim as FAILED_OR_NOT_STARTED; its more
specific interpretation here is FAILED_AT_RUNTIME_IDENTITY_GATE.

The source plan required Python 3.12.3. The existing executable's pyvenv.cfg
records Python 3.14.4. The separately executed original nine-condition
free-generation job also recorded actual Python 3.14.4, Torch 2.9.1+cpu and
Transformers 4.57.3 in its PREEXECUTION (SHA256
`94210824549976c4e2d252ff1fd89c58eca1376efdf8ea42ea29d643ba2a4fdd`).
The successor changes only the exact Python patch version in the plan and
Actions setup to 3.14.4. It does not weaken the version equality check or
change driver logic, tests, weights, tasks, labels, threshold or parser.
Any successor execution uses a distinct durable identity and fresh output.

The raw WORKER_RESULT.json, tests.log, execution.log and pyvenv.cfg are retained
without editing their bytes. SHA256 values are in MANIFEST.json. The terminal
receipt reports failed/exit 1, complete durable output and no truncation.

Actions run 43128410584 on the old source was last observed queued. This
native failure does not determine that CI run's later outcome. No CI pass,
independent future tasks, adapter evaluation or scientific qualification is
credited from this attempt.
