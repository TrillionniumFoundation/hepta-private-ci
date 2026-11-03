# PQ continuation: verified Cell, Windows and historical pair observations

This record independently reads the original artifacts from
[Hepta run 41634290628](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41634290628).
It does not rerun a workload or convert a failed gate into a pass.

## Source identity

| Identity | Exact value |
| --- | --- |
| Hepta source | `a7c523f366de3aaf9bce923be885ad275d0ecc22` |
| Hepta tree | `070d61d7525d55938aa2d6ddcdbf666a138b3125` |
| Hepta base | `3a81000aae08c658276958d678874aca4db5eedd` |
| Actual prospective merge | `f561bfafef1171db955a886227de698e49609913` |
| Historical pair Chain source | `c16507147b65285ea94dead22d3b93c5db7295af` |
| Historical pair Chain merge | `d1b8ae970bb5e014b6feaa49030823e1d8228c90` |
| Separate installed V5 Chain source | `12fe5f2c1f19704fe7eb635dede6839ed8b1e91e` |

The historical pair is not an execution of the installed V5 Chain source.
Any later documentation-only commit does not change these execution identities.

## Completed component observations

Each of the four Linux Cell lanes (x64 and ARM, source and merge) contains
the following actual selected passes:

| Command group | Selected passes in each lane |
| --- | ---: |
| Host material | 23 |
| Real CLI subprocess | 3 |
| arg0 owner | 7 |
| Original owner / FinalUse | 42 |
| Canonical contracts | 195 |
| Exact initial PQ material | 1 |
| Protected initial clock | 1 |
| Original startup deadline | 1 |
| Same-tree Codex PQ turn/start | 1 |

The selections overlap and are not summed as unique tests. The contracts command
runs all 195 cases with zero skips. Other selections retain their exact
out-of-selection counts in [archive-audit.json](archive-audit.json); those counts
are not whole-package zero-skip evidence. No selected retry or failed completion
was observed. The same-tree Codex build record and log hashes match the original
binding. The executable itself is not in these observation ZIPs, so independent
download and rehash of that executable is not claimed.

Both Windows lanes contain 6 selected witness passes and 11 selected
evaluated-shadow passes. Their original minimums are 6 and 7 respectively.
The 11-case observation is retained exactly; it is not relabelled as seven.
Both before/after tracked-source records agree, with no symlink placeholders.
These selected Windows ledger results do not qualify the protected Unix PQ host.

All six ZIP sizes and SHA-256 digests match GitHub's artifact metadata. All
53 Cell command receipts and four Windows test records were checked against
their original log bytes, terminal counts and source identities. Reproduce
the read-only check with `python3 audit_archives.py`.

## Historical pair failure: actual confirmation progress

The original four-second window, seven honest blocks and original gate remain.
All four raw manifests retain `CONFIRMATION_TARGET` and `passed=false`.

| Lane | Baseline confirmation | Last pressure submission | Pressure History pages | Pressure confirmations |
| --- | ---: | ---: | ---: | ---: |
| x64 source | 1.309 s | 2.461 s | 3 / 7 | 0 |
| x64 merge | 1.379 s | 2.552 s | 2 / 7 | 0 |
| ARM source | 1.211 s | 2.350 s | 4 / 7 | 0 |
| ARM merge | 1.210 s | 2.172 s | 4 / 7 | 0 |

Every lane submits all seven honest blocks under pressure. The independent
History consumer does not complete its replay and confirmation in the original
window. Full state equality is false, while the recorded invariants and accounting
close and the verification-error lists are empty. The x64 merge's final History
request retains an I/O timeout and the ARM merge retains `FRAME_DEADLINE`.
These observations locate incomplete progress; they do not isolate a specific
instruction as the cause or establish that a candidate optimization repairs it.

[pair-verified-observations.json](pair-verified-observations.json) is generated
directly from the retained original reports. `python3 verify_pair_payloads.py`
checks each preserved member against its original byte length and SHA-256,
checks the unchanged source records and reproduces the quantitative table.

Each `pair/*.manifest.json` records the official original ZIP identity, all
retained members, and every omitted member. The corresponding `payload.tar.xz`
losslessly retains the current-run non-executable records. The native workload
executable is omitted. The x64 source archive also omits unrelated older Windows
job diagnostics, which remain identified by original member hashes. The complete
original ZIPs are not claimed to be stored in this directory.

## Completed installed V5 job: partial passes and retained failure

The [original installed job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41634290628/job/125929166343)
completed with failure at 2026-11-03 13:15 UTC. Its original artifact is
`13233273505`, 41,009,316 bytes, SHA-256
`cd46b5985d874fc9a292a41270a8b33e257bbd418537fbc76cf6c93a92a3082e`.
The downloaded ZIP matches both its official length and digest.

| Original command group | Actual result |
| --- | --- |
| Artifact controls | 17 passed |
| Execution source controls | 51 passed |
| Diverse source controls | 32 passed |
| Original handoff | 14 passed, zero skipped |
| Protected installed handoff | 8 passed, zero skipped |
| Current PQ startup | 14 passed, zero ignored |
| Current History import/recovery | 15 passed, zero ignored; explicit child fixture remains outside direct counting |
| Current growth CLI | 3 plus 4 passed, zero ignored |
| Current fixed-host controls | 20 passed |
| Current pressure reader controls | 98 passed; original minimum is 86 |
| Original five named native cases | All five process exits are 0 |
| Independent final business gate | **Failed: `CONFIRMATION_TARGET`** |

All 17 original command receipts retain matching complete log lengths and
hashes, clean before/after source identities and original source-specific
commands. The fixed-host controller reports no provisioning or host errors;
the native child itself returns 1 after its independent business gate rejects
the original report. This is an actual business failure, not an incomplete
checkout or a wrapper-only failure.

The current source's baseline independently confirms in **2.809602982 seconds**.
Under pressure all seven blocks have been submitted by **1.879015810 seconds**.
Two History responses arrive, but the independent verifier accepts only the
first page; the second replay returns `PUBLIC_REQUEST_DEADLINE` and no transaction
is confirmed inside the original four-second window. The accepted replay takes
75,876,840 ns of caller-thread CPU and 1,302,096,479 ns of wall time; the failed
replay consumes 30,567,533 ns of caller-thread CPU and 499,334,547 ns of wall time.
These CPU intervals exclude separately owned worker CPU. They are observations,
not proof that a particular optimization closes the original gate.

[installed-verified-observations.json](installed-verified-observations.json)
retains these counts and replay timings. `python3 verify_installed_payloads.py`
checks the preserved original bytes and reproduces the observations. Three
`installed/*.tar.xz` payloads preserve every non-executable member of the original
ZIP, including all nine original SQLite snapshots. The three binary payloads
are omitted with explicit lengths and hashes in
[binary-hash-observations.json](installed/binary-hash-observations.json).
The original Cell and PQ Node gzip files were independently decompressed and
hashed; the Cell image agrees with the installation record. The transferred
Hepta daemon remains bound by its original same-run import and installer
records; its separate 489,017,776-byte image was not independently downloaded
for this follow-up.

## Acceptance limits

The completed installed observations close the missing observation for their
listed stages. The installed business loop remains failed. No result from the
historical Chain pair is substituted for the current-source replay failure.

The ARM complete Node CPU-budget failures, historical pair confirmation failure,
all-state rollback/migration, independent deployment/WAN evidence, complete
authorization/release/governance/recovery roots, proof PQ-128 argument and
full neural-work quantum-cost argument remain separate obligations.

`whole_system_qualified=false`, `pq_128_qualified=false`,
`production_activation=false`. The paired pull requests remain drafts.
