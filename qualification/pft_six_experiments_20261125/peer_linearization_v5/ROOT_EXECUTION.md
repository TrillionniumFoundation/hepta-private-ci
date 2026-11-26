# V5 fixed two-host rational equation round

Status: **inactive, unexecuted source proposal**. The author performed reads and source edits only. `PEER_STEP_AGREED` is an endpoint output label; independent auditing must verify its contents. Original E1–E6 remains 16/16 exhausted. This work does not rerun that matrix.

## Scope and mathematical contract

Each host gets one retained V4 row, computes its own unregularized G/b/c, exchanges those statistics through an existing direct SSH connection, independently solves the six-coordinate quadratic, and compares step hashes. Main supplies bootstrap files and collects completed receipts. It does not forward contributions between participants.

Both rows came from one retained synthetic batch. They are not independent users or independently collected datasets. The original derivative diagnostic remains FAILED. This proposal explicitly uses its midpoint primitive-VJP surrogate without classical or Clarke Jacobian certification. Data rank is 2 and nullity 4; regularized solver rank 6 does not identify the four unobserved directions.

Every numeric row value becomes its exact binary64 rational with `Fraction.from_float`, including lambda=old binary64(0.001), which is not silently decimal 1/1000. Each node computes G=w JᵀJ, b=w Jᵀ(target-base), c=w(target-base)² with no local ridge. The two contributions are summed and ridge is added exactly once globally. Six-dimensional rational Gauss-Jordan must give exact zero normal-equation residual. The unregularized rank check remains 2.

The wire represents reduced fractions by canonical decimal numerator/positive-denominator string pairs, bounded to 2,048 bits after each material arithmetic result. Each local joint matrix [[G,b],[bᵀ,c]] requires an exact nonzero rank-one PSD certificate. This proves algebraic consistency, not private-data honesty.

Both peers record the exact step and a single componentwise CPython conversion to binary64. Each quantization error must be at most half an ulp. Exact rounded-step stationarity must be ≤ binary64 1e-12 and the rounded step norm ≤ 1 without clipping. Predicted reduction uses the rounded step and the one global ridge. The delta SHA matches the existing `<f8`, shape `(6,)` array convention. Nonlinear benefit and candidate identity require separate downstream verification.

## Verified transport lineage and new ownership

The old successful direction was **ai395 → pocket4**. Source: commit `4c40e8a7b11a1f2afd661f2b76dd3929a3f41edb`, `qualification/pft_six_experiments_20261125/p2p_closure_v2/ssh_runner.py`, SHA-256 `e860287e58562531566d3c4ff90f71beba5df9a1d46cd19862b9d2939d337f7f`. Success receipts are `discovery/pft_v4_ci/cost_sources/p2p_closure_v2/results/pft2_direct_peer_ssh.json` and `discovery/pft_v4_ci/cost_sources/p2p_real_hcsn_pretest_audit.json`.

Read-only inspection confirmed ai395 `/home/qq/.ssh/hepta-transport/ssh_transport.py` still has the old SHA `62806672b699d794e2fe9c738a281727fa1fd6595266440a747f8a4145d449e9`. It passes a connected TCP socket to OpenSSH using `ProxyUseFdpass=yes` and does not relay application bytes. Existing USB4 selection is `10.77.0.2 → 10.77.0.4:22`, bound to `br-usb4`. Alias `pocket4` uses user `alex`, HostKeyAlias `hepta-node-pocket4` and strict public known-host pins. Private key content was not read. The known-host and inventory hashes are in `ROOT_PREFLIGHT_CONTRACT.json` and `SSH_TEMPLATE.json`.

Only root may register and create these fresh directories:

| Host | New root |
| --- | --- |
| ai395 | `/home/qq/pft-peer-linearization-v5-20261126-8a32` |
| pocket4 | `/home/alex/pft-peer-linearization-v5-20261126-8a32` |

Each root receives `code/` containing only the unchanged V4 `profile_io.py` plus proposed `exact_equations.py` and `peer.py`. Each `round_01/` receives identical active `common.json` and its own single `row.json`. Only ai395 receives `ssh.json`. Do not deploy the whole V4 record, the other row, a prior central delta, or the prior accepted candidate to these run directories. Preserve other roots' directories and services, all reserved ports, and existing SSH configuration.

## Minimal read-only preflight

`ROOT_PREFLIGHT_CONTRACT.json` remains inactive. Root registers one metadata probe. Recheck the proxy, inventory and known-host hashes; record ai395's local hostname and selected CPython version without importing model/project code. Effective `ssh -G pocket4` metadata can be inspected without a live connection.

The provided standalone `preflight.py` implements this probe using only the Python standard library. Root deploys its formatted, hashed bytes and launches it once on ai395 with the selected CPython and `-B`; it takes no arguments, performs no file writes, and outputs one metadata JSON record (≤64 KiB) with lossless base64/sha256 of remote stdout and SSH stderr. It has a 12-second body alarm and bounded 2-second cleanup under root's 15-second outer deadline. The template stays inactive until root registers that one invocation.

Reuse the strict options and proxy direction from `peer.ssh_command`, including `ProxyUseFdpass=yes`, no agent/port forwarding, no multiplexing, one connection attempt and 8-second connect timeout. For this preflight only, replace the peer entry point with this remote argv, safely shell-quoted by `shlex.join`:

```python
[
    "/home/alex/pft-six-actual-hcsn-20261125/venv/bin/python", "-I", "-B", "-c",
    "import json,os,platform,resource,signal,socket,sys; "
    "resource.setrlimit(resource.RLIMIT_CPU,(2,3)); signal.alarm(8); "
    "print(json.dumps(dict(hostname=socket.gethostname(),uid=os.getuid(),"
    "executable=sys.executable,python=platform.python_version(),"
    "implementation=platform.python_implementation(),"
    "ssh_connection=os.environ.get('SSH_CONNECTION','')),sort_keys=True))"
]
```

Root's supervisor bounds total wall time to 15 seconds, stdout to 4 KiB and stderr to 16 KiB, preserving exit status and raw proxy selection. Avoid unbounded `communicate()` capture. Success requires exit 0, one direct selection of USB4 with interface-bound `br-usb4`, source/destination `10.77.0.2/10.77.0.4`, and remote SSH_CONNECTION confirming those endpoints and port 22. No scientific arithmetic, model reads, directory creation, listener or automatic retry belongs to the probe. Historical success alone is not current reachability evidence.

## Root execution sequence

1. Finish static review and required formatting. Record hashes of final formatted source. Preserve all historical records and failed controls.
2. Admit the single metadata preflight and retain its result. Fill `ENVIRONMENT_TEMPLATE.json` with the actual hostnames and CPython versions. A different/unreachable route refuses the attempt; it does not authorize substituting hosts.
3. On main only, run `prepare_rows.py` with `--retained publication/v4/retained_nonsmooth_peer_01.json`, `--profile-io discovery/native_profile_v4/profile_io.py`, `--environment FILLED_ENVIRONMENT`, and a fresh `--output ROOT_STAGING`. It verifies whole-record SHA `81dc97a289e3f00089998deea5094fe46591b7736d946e98b77e4bed7378b263`, copies each of the two exact retained local rows, copies protocol sources, and writes an **inactive** common document. It performs zero solves, forwards and model imports.
4. Register exactly one new round `pft-v5-rational-usb4-20261126-8a32-01`, with all budgets and pins. Store admission separately; insert its SHA into `common.root_admission_sha256`, set `active=true`, serialize canonical JSON, and compute active common SHA. Common has parent/profile/source/coordinate identities, derivative-failure provenance, row hashes and metadata only; no row target or Jacobian values.
5. After ownership registration, create only the new host roots, deploy permitted files and verify readback hashes. No whole-record reference or precomputed step goes to a participant. Existing SSH dependencies remain unchanged and must still match pins.
6. Launch on ai395: `CHOSEN_AI395_PYTHON -B NEW_AI395_ROOT/code/peer.py --node ai395 --root NEW_AI395_ROOT/round_01 --common-sha256 COMMON_SHA --ssh-sha256 SSH_CONFIG_SHA`. This node launches one remote pocket4 endpoint over direct SSH. Main never pumps contributions. Exclusive `run.claim.json` refuses same-round relaunch.
7. Collect both result files and any failure/process/CPU/wall records. Independently verify source/common/input pins, actual endpoints, identical step objects, A.sent=B.received and B.sent=A.received for every frame, correct per-row G/b/c, exact stationarity and rounded-step encoding. Neither a success label nor a central solve substitutes for this audit.
8. Bind the whole ai395 result-file SHA as `learning_receipt_sha256`, with pocket4 result and common SHA also pinned, to the separately admitted aggregate candidate gate. That gate materializes this exact rounded step against the original parent, performs its own actual nonlinear reduction check, exports its own full candidate, and runs its own independent cold verification. Old central acceptance/cold results cannot confer acceptance on this candidate, even if deltas/tensors are equal or close. This protocol grants no adoption.

## Budget and lifecycle

| Item | Bound |
| --- | --- |
| Peer round | 1, no restart/retry |
| Hosts / exact solves | 2 / 1 per host |
| Model imports, loads, forwards, VJPs | All 0 |
| Dimension / observations | 6 / 2, one row per host |
| Application frames / bytes | 6 / ≤393,240, including 4-byte prefixes |
| Frame cap / result cap | 64 KiB / 256 KiB |
| Common / row / config / source read caps | 32 / 16 / 16 / 64 KiB |
| SSH stderr / failure-file cap | 16 KiB / 4 KiB |
| Python CPU | 10-second soft, 11-second hard, per process |
| Address space / open descriptors | 256 MiB / 64 per process |
| Node wall | ai395 50 s, pocket4 45 s |
| Root outer wall | 60 s including cleanup |
| New listeners / model state writes | 0 / 0 |

SSH and its socket selector inherit per-process CPU limits. Process-family CPU must be reported separately; this is not a 10-second aggregate CPU claim. SSH/TCP negotiation/transport overhead is separate from measured application frame bytes. Local and remote wall times overlap and are not additive wall cost. Subsequent nonlinear/cold work has separate budgets.

Three ordered frames per direction carry hello, contribution and step confirmation. Canonical bodies are hashed; schema, fixed common hash, sender/recipient, sequence and kind reject another round, duplicates or reordering. The ai395 transport receipt preserves the complete bounded original SSH stderr in base64 with its SHA and parsed selector receipt. Any error, overflow, timeout, mismatched route or unsuccessful child exit stops the attempt and retains its claim/failure evidence. No crash-resume result is inherited from old P2P work. The minimal protocol does not establish Byzantine resilience, privacy, Sybil resistance, permissionless availability, or independent-user adoption.

The Linux launcher observes the SSH leader with WNOWAIT, keeps its PID unreaped while killing only its own new process group, then uniquely reaps it and closes bounded streams. No unrelated PID/group is targeted. The remote Python also has its own wall alarm. This is deliberately a fixed Linux/SSH research harness, not a new service or portability framework.
