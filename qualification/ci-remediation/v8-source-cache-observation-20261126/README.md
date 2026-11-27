# Observe the existing source-cache refusal conditions

## Original result

The `be271dd` Windows source-build jobs `139669167575` (ARM64) and
`139669167650` (x64) both reached the original 20-minute build-step limit.
Their full logs have SHA-256
`dfef690e8567323c985026abc777b39b9bb63d1356d827dbd8444df9748fbd9a`
and `94f205b3d118da555edf45dc50499a320b5d9186378ff9b7f1567ab467b60142`.
The last reported Ninja positions were 1388/4431 and 1377/2421. These are
observed progress counts, not completion estimates or a new performance result.

Both compatible-cache restores missed. The subsequent check printed its
combined refusal warning, and both cache-save steps were skipped. The old
output does not distinguish a nonzero `sccache --stop-server` exit status from
one or more matching process names in the existing single process enumeration.
No Windows source build, staged artifact, smoke check, or cache save passed.

## Diagnostic-only change

Print the original stop status before process enumeration. After the existing
enumeration and filter, print the original matching-process count and the
matching names drawn from the existing fixed twelve-name allowlist. Each name
appears at most once in the summary, so it is bounded independently of the
number of processes. No PID, command line, environment, unrelated process name,
or file content is emitted.

There is still exactly one `Get-Process` call with `-ErrorAction Stop`. The
original refusal condition and `ready` outputs are unchanged. This adds no
second enumeration, polling, wait, process termination, retry, permission, or
cache-admission exception. The original 30-minute job limit, 20-minute build,
one-minute check, three-minute save, cache-key expressions, and smoke gates remain.
The workflow itself is a hashed input, so its changed bytes produce a new
compatibility fingerprint. This does not promise a hit on the earlier cache key.

The pinned sccache 0.8.2 source returns its stop reply before the server's
separate service-drain stage has necessarily finished. A successful stop
command is therefore not proof that the server or compiler children exited.
This source fact permits an observation window; it does not establish the
cause of either original refusal. The name snapshot is also neither an atomic
absence proof nor an ownership proof for this job.

No PowerShell or native execution has run for this candidate. Formatting,
workflow lint, and source comparison cannot qualify the source build or cache.
Actual observations from a subsequent normal run are still required.
