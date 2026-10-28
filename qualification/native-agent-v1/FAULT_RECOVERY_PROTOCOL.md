# Launched-tool crash and owner-restoration experiment

Run one fresh `sum` case for each of `native`, `app-server`, and `facade` using
`fault_recovery.py`, with a new output directory for each run. This is a
correctness experiment in fixed-response replay mode, separate from latency,
CPU and memory qualification samples.

## Fixed fixture and operation

The experiment copies the frozen fixture data unchanged into its private run
directory. The script is the same original fixture with `import time` and
`time.sleep(5)` prepended. Its new SHA-256 is admitted through the normal
qualification configuration. All arms use these same script/data contents.
The delay makes the launched-but-unfinished interval observable; it is not a
model-produced command and does not alter the tool's expected stdout.

The model gateway remains alive at the same URL. The runner configuration file,
session, prompt, original call ID, model arguments, admitted compiled process
parameters, runtime idempotency key and generation must remain unchanged.

## Exact fault boundary

The watcher waits for exactly one controller job with
`launch_state == "launched"`. It also verifies the full request digest against
the owner's admitted compiled payload, finds the corresponding remote request
and actual fixture-child record, and confirms `exit.json` is still absent.
The owner checkpoint must contain the original pending tool with
`submission_attempted == true`, `cancel_requested == false`, and no pending
model response or final answer.

Only then does the watcher issue SIGKILL to the `Popen` object that this script
created for its runner/helper. It never signals a process group, systemd unit,
fixture child, or PID obtained from runtime metadata. Success requires the
owned runner's return code to be `-SIGKILL` and its protocol stream to end in EOF.
A naturally exited runner, already-returned result, missing injection point,
unexpected protocol error, or timeout does not qualify as an injected fault.

Fault scope is explicit:

- `native`: kill and restart the whole native runner, including its model/tool
  loop and embedded runtime bridge.
- `app-server` and `facade`: keep the original Codex process and original turn
  alive; kill and restart only its persistent runtime helper.

This tests the relevant owner-restoration path for each composition. It does
not claim that an entire Codex App Server or facade process was crashed.

## One restoration, no effect replay

Following that verified injected EOF, the wrapper may start one replacement
runner with the identical configuration and resend the exact original
qualification command. The command's serialized SHA-256 is recorded before
and after. This re-enters the existing session owner; it does not construct or
send a new `process_start` operation. The durable `submission_attempted` state
requires observation of the original runtime job.

No other exception permits a restart. A second failure or pending outcome is
retained as negative evidence. The script never deletes state, changes session
identity, resets the model gateway's call sequence, or invents another key.

## Passing evidence

A positive report requires all of these checks:

1. A verified SIGKILL/EOF boundary and exactly one replacement runner.
2. The same controller job ID, request digest and complete metadata, exactly one
   controller job, and exactly one physical remote job directory.
3. Unchanged remote request and fixture-child record hashes, as well as unchanged
   session manifest, owner binding, tool admission, compiled parameters and all
   previously admitted model requests.
4. The restored owner terminally consumes that original call. Native retains
   its root operation ID/generation and has exactly two original model calls.
5. The model gateway captures exactly response calls 1 and 2, without a request
   retry or replacement response, and the exact shared-tool inventory.
6. The normal benchmark audit binds the final answer to the real original
   `hepta_probe` result, including integer zero exit, exact stdout and empty
   stderr. Missing or incomplete evidence fails.
7. In each Codex arm the same Codex process remains alive through completion of
   the original turn; only its runtime helper has restarted.

`BEFORE.json`, final `REPORT.json`, process protocol logs, owner checkpoints,
controller/remote job files and captured model requests remain available for
review. Partial, pending, failed, or uninjected runs stay negative and must not
be discarded when summarizing outcomes.

This single crash point does not cover a lost launch acknowledgement before
controller publication, model-provider stream loss, tool-process failure,
corrupt checkpoints, cross-host migration, or every cancellation race. Those
need their own fault cases; passing this one does not imply general exactly-once
execution or complete production recovery qualification.
