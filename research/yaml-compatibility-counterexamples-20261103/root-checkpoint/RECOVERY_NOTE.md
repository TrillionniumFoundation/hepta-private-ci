# Source and log provenance limitation

These bytes were restored from the exact v3 checkpoint by the root agent after the execution environment reset. The snapshot contains expanded source. `adapter-candidate.log` is a historical narrow 14-PASS observation without a verified binding to the current expanded source; it must not be called a pass for that source. Before reset the expanded source was actually executed and gave 13 PASS / 1 FAIL, but the complete expanded failure log was lost. This copy preserves the checkpoint rather than overwriting its evidence.

The root wrapper SHA256 is `3f8ead66b64e10d090c7857d6ad17c44c9484400ad7c903016374cb58dcd4e30`, matching the pre-reset independently recorded hash. Recovered checkpoint files are not a new execution receipt.
