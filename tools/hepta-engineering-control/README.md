# Hepta engineering control

This source root provides deterministic, bounded work-envelope scheduling and
integration eligibility. It deliberately has no merge, deployment, runtime,
promotion or release capability.


## Disposable single-service process slice

`assimilation/owned_service.py` runs exactly one reviewed, unprivileged counter
service, not arbitrary commands, systemd units or package managers. It owns a
private 0700 directory and a bounded SQLite operation table; the client owns only
the child handle and observations. Readiness binds the actual PID, UID, directory
inode and generation. The child holds the exclusive writer lock, commits before
acknowledgement and accepts stable operation IDs. Lost acknowledgement stays
indeterminate; `reconcile` reads the prior result without dispatching again.

Run as a non-root user:

```sh
python3 -B -m unittest discover -v -s tools/hepta-engineering-control -p test_owned_service.py
```

The tests start real processes, commit and reopen actual SQLite state, kill a
process after commit but before acknowledgement, reject a second writer, preserve
operation identity across restart and reject state older than a supplied minimum
counter. The minimum must be retained independently by the host. These tests do
not discover or control live Debian services, enroll another host, install
packages, grant authority or certify a hostile-code sandbox. They add an executed
single-service software-in-loop target under the existing ASM work packages;
owner-authorized live service adaptation, full state migration and deployment
remain separate work.

### Bounded stateful service upgrade

The owned counter has two compatible implementation profiles. Version 2 adds
`origin_generation` using the same SQLite writer. Schema migration and the
persisted generation fence commit together while the existing exclusive file
lock is held; an independent counter frontier is checked before this commit.
A predecessor cannot restart after a committed successor migration.

The `before_commit` and `after_commit` fault modes terminate a real child at the
migration boundary. Rolling back code means starting version 1 at a newer body
generation on the current version-2 database; it never restores an old snapshot
or drops post-upgrade operations. This demonstrates one additive service-domain
migration, not arbitrary writer handoff, destructive schema downgrade, systemd
control or host enrollment. Tests run as an unprivileged user.
