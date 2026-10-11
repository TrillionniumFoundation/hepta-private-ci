# Trillionnium OS external evidence admission

Status: **source candidate only; unprovisioned; no target, promotion, or release authority**.

This directory preserves the ordinary admission/executor source from commit
`3999c9d3101aa5c7501d48cc56101b1b3e7b8dc9`, plus the separate earlier review
regressions. Exact source blobs are retained in `SOURCE_ORIGIN.json`. It is an
optional Linux Python 3.11+ evidence-capture tool, not the Trillionnium OS runtime,
a Debian bridge, a publisher or a Hepta controller. No daemon startup, policy
provisioning, external target contact or automatic discovery is added by this
migration. Existing fixed installation paths remain unchanged for compatibility.

The latest executor supersedes older one-process-group cleanup with subreaper
and pidfd descendant handling, checks authority even after output pipes close,
and durably records failure at every post-STARTED stage. Historical regression
injections now occur after the actual durable STARTED write and check separate
primary/fallback stores. An invalid preexisting result cannot be overwritten or
treated as success. Original causes remain available through exception chains;
public failure records use stable stage codes rather than arbitrary exception
text. Temporary test harnesses and ephemeral fixture signing keys are the only
executables/credentials used in source verification.

`admission_service.py` implements the independent boundary between the
repository route request and a target-owned harness. It opens root-owned inputs
nonblocking, rejects special files before reading, and closes each descriptor on
every partial-acquisition or malformed-policy failure. It rejects
duplicate/non-finite JSON, verifies exact request/grant binding, requires a
strictly positive bounded grant lifetime, and compares approvals and operational
roles case-insensitively. L5/L6 policy requires two independent approvals.

RSA-SHA256 verification runs over the retained grant bytes through sealed Linux
memfds. A successful admission atomically writes one nonce-consumption record
before any target contact.

The checked-in policy is deliberately `UNPROVISIONED_TEMPLATE`: its key digest
is zero and issuer allowlist empty. An external custodian must install an
`ACTIVE` root-owned policy and public key under `/etc/owner-open-r5`, and must
provision `/var/lib/owner-open-r5/admission` mode 0700. Repository authors or
workflows must not populate the trust root.

This stage does **not** allocate a runner, contact a device, execute candidate
code, execute a harness, produce target evidence, review evidence, change a gap,
or authorize release. The next stage may consume the immutable admission record
and fixed target files, but it must use a separate one-shot execution marker.

Source verification:

```bash
cd tools/hepta-os-evidence
python3 -m unittest discover -s tests -v
```

The native CI gate uses `python3 run_native_tests.py` in this directory. It
requires matching procfs/PID namespaces and pidfd support and rejects any skipped
test. The file entry point and `__main__` guard let multiprocessing's `spawn`
reload the runner without executing the suite inside each inspection worker.
Do not run this gate through a Python stdin heredoc: `<stdin>` cannot be reloaded
by a spawned worker and causes legitimate captures to fail bundle inspection.

Production entrypoint after independent deployment:

```bash
/usr/bin/python3 -I /opt/owner-open-r5/admission_service.py \
  --request /secure/inbox/request.json \
  --grant /secure/inbox/grant.json \
  --signature /secure/inbox/grant.sig
```
