# Five private Agentd enum qualification

The corrected candidate `391b379f5225d28db21580f1df526a31f761dd2a` passed 27 ordinary and 30 actual UID0 original native tests. The baseline `d1ab8c895dbdceda956f7765da36e07a71c7f760` passed 27 ordinary and 29 of 30 UID0 tests on two distinct runners, with the same original queued-cancellation readback assertion failing. The paired native job was red. The original strict gate went from 124 to 119 diagnostics and remained exit 101. Exactly five private enum findings disappeared, with no additions.

`evidence.zip` contains both attempts' four raw GitHub Actions ZIPs, source and diagnostic replayers, exact fixture names, source hashes and the observed individual tests. The outer ZIP has 172,360 bytes and SHA-256 `426bd72b2cfe81459ec0c88364344a48cdd4574b8f7ca7157166462d1d0c0146`. Extract into an empty directory and run `python3 verify_results.py strict.zip native.zip`. See the included README for source-guard replay and precise scope.

[Original attempt](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45131004390) · [Corrected paired jobs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45132769603)
