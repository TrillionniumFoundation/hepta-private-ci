# H4 persistent writer / physical power-cut runbook (2026-08-26)

This is an opt-in test procedure for a dedicated Hepta Agent store. It must
not be run against the active Agentd fleet, production provider credentials,
Dropbox, or a shared cognitive database. A human-approved test window is
required before any physical power action. The commands below do not cut
power; they only prepare, monitor, and recover.

## Current host audit

`claw-j3160` and `newpc-lan` currently resolve to the same machine
(`192.168.0.8`; use `qian@100.66.117.33` explicitly for the Tailscale path).
The machine is Ubuntu 24.04.4 on an Intel Celeron J3160 (4 cores, 3.7 GiB
RAM), with one Colorful CM300 SATA SSD. `/sys/class/power_supply` is empty.
No `upsc`, `apcaccess`, NUT, `ipmitool`, `smartctl`, BMC, UPS, PDU, or remote
outlet controller was found. SSH/Tailscale are in-band only and disappear
when the host loses power; the router and the monitoring machine must be on a
separate powered circuit. The recent reboots were clean SIGTERM/systemd
shutdowns and are not power-loss evidence.

The SSD currently reports:

```text
/sys/block/sda/queue/write_cache = write back
/sys/block/sda/queue/fua         = 0
```

Therefore SQLite WAL + `synchronous=FULL` is an OS/filesystem durability
boundary, not proof that a volatile device cache survived power removal.
Media-level durability remains `BLOCKED` until a PLP-capable device, a
verified cache policy, or an approved storage/UPS design is supplied.

## Code and harness

The isolated integration branch contains the opt-in example:

```text
codex-rs/hepta-agentd/examples/h4_persistent_writer.rs
```

It uses `AgentdProductionWriterHost::open_with_store`, admits one queued
occurrence, atomically writes `h4-persistent-prepare.json`, and waits for an
operator gate. A new `recover` process reopens the same WAL/FULL store,
checks exact event/outbox replay, runs indeterminate → rollback → release,
and writes `h4-persistent-recover.json`. It records boot IDs, SQLite
`journal_mode`, `synchronous`, `integrity_check`, row counts, and Linux block
device cache observations. It is not wired into Agentd startup and all of
`external_effect`, `production_caller`, `kg_write_authority`, and
`physical_power_loss_claim` are hard-coded false. The harness's authority is
an explicitly labelled local qualification verifier, not an external trust
root.

Build/check on the isolated Mac branch (not the active main worktree):

```bash
cd /Volumes/T5/hepta-vnext/worktrees/azi2-authority-integration-20260826/codex-rs
TMPDIR=/private/tmp cargo check --offline -p codex-hepta-agentd \
  --example h4_persistent_writer
```

The resulting binary must be built for the target host. A macOS/arm64 binary
cannot be copied to the x86_64 J3160; build the example on the J3160 from the
same reviewed commit, or use a reviewed x86_64 cross-build.

## Phase A: prepare (no power action)

Use a fresh, local, non-root directory on the J3160 and stop before the
operator gate. `H4_WAIT_SECONDS=0` (the default) waits indefinitely; the
marker is durable before the process waits.

```bash
export H4_PERSISTENT_ROOT=/home/qian/h4-cut-20260826-run1
export H4_QUALIFICATION_TOKEN='<operator-supplied test token>'
./target/release/examples/h4_persistent_writer prepare
```

Record the printed marker and verify that
`$H4_PERSISTENT_ROOT/h4-persistent-prepare.json` exists. Do not reuse a root
with an existing marker. The marker must show `journal_mode=wal`,
`synchronous=2`, `integrity_check=ok`, and `physical_power_loss_claim=false`.

## Phase B: independent monitoring

Start monitoring from a separately powered Mac/host before the cut. Save the
log outside the J3160 test root. This is only reachability evidence:

```bash
run=/private/tmp/h4-cut-monitor-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$run"
while :; do
  ts=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)
  if line=$(ssh -o BatchMode=yes -o ConnectTimeout=2 qian@100.66.117.33 \
      'printf "%s %s\\n" "$(cat /proc/sys/kernel/random/boot_id)" "$(uptime -s)"' \
      2>/dev/null); then
    printf '%s up %s\\n' "$ts" "$line" >>"$run/reachability.log"
  else
    printf '%s down\\n' "$ts" >>"$run/reachability.log"
  fi
  sleep 0.5
done
```

Keep the monitor, router, and any PDU controller on a different outlet from
the J3160. There is no verified remote power control on this host, so do not
invent a `poweroff`, IPMI, or smart-plug command.

## Phase C: approved physical cut (manual only)

Only after the marker is present and the test window is approved:

1. Confirm the BIOS setting **Restore on AC Power Loss = Power On** (or have a
   person physically present to press the power button after restoration).
2. Confirm that no production process/provider is using the test host or
   database, and that the monitor/router remain powered.
3. Have the operator remove AC from the J3160 test outlet for a recorded
   interval (10–30 seconds is sufficient for a cold boot), then restore AC.
4. Do not use `systemctl poweroff`, SIGKILL, VM pause, or SSH termination as a
   substitute. Those are separate crash/reopen cases.

## Phase D: recover and collect evidence

After the host is reachable again, record the new boot ID and previous-boot
logs before running recovery:

```bash
ssh qian@100.66.117.33 'cat /proc/sys/kernel/random/boot_id; \
  journalctl --list-boots --no-pager; \
  journalctl -b -1 -n 120 --no-pager'
```

Then run recovery with the same test root and token. Set the operator flag
only after the human has confirmed that the AC was actually removed; it does
not turn the receipt into an independent signature:

```bash
export H4_PERSISTENT_ROOT=/home/qian/h4-cut-20260826-run1
export H4_OPERATOR_CONFIRMED_CUT=1
./target/release/examples/h4_persistent_writer recover
```

The recovery receipt is valid only if it records exact replay (`replayed=true`,
same `event_id`, `outbox_id`, and payload digest), `integrity_check=ok`,
WAL/FULL, and a terminal release with all effect flags false. A changed boot
ID plus monitor loss and an abrupt previous journal are evidence that a cut
occurred; they are not by themselves a claim about SSD media durability.

## Receipt fields and acceptance

Archive the prepare marker, recovery receipt, monitor log, pre/post boot IDs,
previous-boot journal excerpt, commit hash, binary hash, and cache-state
snapshot. The minimum machine-readable fields are:

```text
boot_id_before, current_boot_id, boot_id_changed
operator_confirmed_cut, physical_cut_observed
journal_mode, synchronous, integrity_check
cache_devices[].model, cache_devices[].write_cache, cache_devices[].fua
lease_rows, event_rows, outbox_rows
replayed, status_before_terminalization, release.state
external_effect, production_caller, kg_write_authority
physical_power_loss_claim
```

Run at least **N >= 3** trials, each with a fresh root/generation and a
different deterministic cut point (after prepare/admission, after a local
terminal transition, and after reopen). Acceptance is split:

- **Crash/reopen:** exact replay + WAL/FULL + integrity pass. This can be
  proven by the existing SIGKILL/child harness and does not require a power
  controller.
- **Physical interruption observed:** independent monitor sees the outage,
  boot ID changes, and previous boot ends without a clean shutdown; recovery
  still passes. This requires the manual/PDU cut above.
- **Media-level power-loss durability:** remains blocked until the SSD cache
  policy/PLP is independently established. Never rewrite this gate as cleared
  from a SIGKILL, `fsync`, or one clean reboot.

No physical cut was executed while preparing this runbook.
