# One-round SSH statistic delivery qualification

This is a separate engineering protocol. The original E1–E6 scientific panels,
their remaining budgets, the original LAN/overlay failures, and the later
45-second TCP/38653 USB4 failure remain unchanged. No scientific matrix, original
training/evaluation job, or old CI run is restarted by this entry.

The existing hosts already allow and mutually authenticate SSH on USB4 port 22.
Their installed `ssh_transport.py` validates an administrator-configured peer
inventory, binds the registered interface and source address, and passes the
connected descriptor to OpenSSH. It does not relay application bytes. This entry
preserves that guard, existing private keys and `known_hosts`. It disables agent
authentication/forwarding, passwords, interactive authentication, multiplexing,
port forwarding, local SSH commands and host-key updates. A guarded selection of
any fallback endpoint fails this qualification even if SSH itself succeeds.
Ambient SSH configuration is excluded; the already observed account, address,
port, identity file, host-key alias, trust file and guarded inventory are supplied
explicitly. This preserves the existing transport guard while preventing
unrelated `Match exec` or `KnownHostsCommand` callbacks.

## Fixed protocol and evidence

The initiating application starts the exact source-pinned `ssh_snapshot.py` at
the other registered host, with its independently pinned configuration. There is
no configurable shell callback. Both application processes derive their own one
contribution from their own original compressed archive, selecting only n=8,
seed=731. Neither process receives the other host's archive through the control
plane. The control plane deploys public code/configuration, schedules the
initiator, and collects completed evidence afterward.

The duplex SSH stream exchanges hello, contribution, independently calculated
summary, commit and completion frames. Every frame carries a fixed round,
context, exact sender/recipient and monotonically increasing sequence. Prefixes
limit each JSON body to 64 KiB; duplicate keys and nonfinite JSON constants are
rejected. Both directions share their process's one absolute monotonic delivery
deadline. A fragmented frame cannot restart it. The initiating session has a
45-second deadline covering SSH startup and application exchange; the responder
also imposes a single 45-second bound and exits immediately on a closed pipe.
Child termination and reaping may consume up to four additional seconds, with
one additional bounded 0.1-second diagnostic join. SSH stderr is capped at
64 KiB; overflow terminates the initiating process's owned SSH group.

Each host retains the exact application frames and SHA256s, actual process/boot
identity, `SSH_CONNECTION`, strict Receiver ledger, frozen snapshot, numerical
candidate and terminal status. The initiator also retains the exact SSH argv,
owned child PID, original bounded stderr, matched host/client public-key
fingerprints, and the guard's actual local/remote socket addresses and required
interface binding. Source addresses establish observed paths; SSH keys establish
the authenticated host/account channel. This does not establish data ownership
or resistance to an administrator who controls an enrolled host.

## Numerical comparison and candidate identity

Each host accepts both exact pre-admitted contribution IDs and payload hashes
through `distributed.Receiver`, orders the sums identically, freezes the round,
and independently solves the ridge objective. It also solves in the eigenvector
directions of the received aggregate, reporting effective rank, discarded target
norm, relative solve difference, and the normal-equation residual.

The central reference is the already published n=8/seed=731 audit grid in
`results/pft2_multihost.json`. Its entire artifact and selected grid are checked.
No new central data generation or scientific evaluation is performed. The new
protocol explicitly defines canonical candidate weights on that original 1e-10
grid, so both peers can commit the same weight bytes while preserving their
unrounded solutions and relative errors. A comparison to the central grid
includes quantization error and must not be presented as a full-precision
central-solve error. A full effective rank of eight demonstrates no dimensional
reduction or speed advantage for this case.

Successful delivery would close only this particular authenticated two-host,
fixed-statistic exchange and numerical consistency check. It would not convert
the failed unencrypted TCP attempt into success, show WAN consensus, train a
foundation model, establish task improvement, demonstrate real-user adoption,
or justify settlement. Failed prerequisites and delivery costs remain in the
separate admission's evidence and are included in the system cost accounting.

## Local controls

`test_ssh_snapshot.py` uses two independent processes connected by ordinary OS
pipes, with explicit local-only identity fixtures. It never claims these are SSH
hosts. It checks complete original-statistic exchange, matching snapshots and
candidate bytes, original frame retention, absolute fragmented-frame deadlines,
oversized framing, sequence replay, pinned-roster/source/reference substitutions,
wrong contribution owners, relay endpoint rejection, and bounded termination of
a child that ignores SIGTERM. Existing TCP/Receiver controls are not scientific
panel runs.
It also checks a terminal SSH leader whose descendant still holds stderr, and a
configuration replaced between its file read and parsing. Diagnostics use a
nonblocking raw descriptor and bounded stop polling; a terminal leader does not
exempt the invocation's remaining process group from cleanup.
