# Original MemoryCell startup suite

The initial full native run on c6a selected 1,552 of the 1,723 original Agentd cases. It passed 1,547. Five cases failed to locate hepta-joint-propose. The previous failure requiring codex passed. Both child binaries and the Agentd libtest had already been compiled and their identities verified. The original POSIX recipe shell discards environment-variable names with a hyphen on the runner. The existing binary resolver also recognizes the underscore form.

A fresh hosted Linux runner used the exact same three native binaries from the same 289,596,298-byte build artifact and the same checkout. With the underscore environment name provided, each of the 1,552 originally selected cases passed. The 171 existing ignored cases kept their flags. The four explicit control groups ran 6, 3, 6 and 2 cases. The offline comparison checks every ZIP member, each test name and outcome, the six originally affected cases, archived and restored roster equality and the five build artifact hashes. The original time limit was 30 minutes in both cases. Both raw ZIPs are included.

| Source | Job | Evidence |
| --- | --- | --- |
| c6a build | [137527725126](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165645/job/137527725126) | compiled.json, verify_compiled.py |
| c6a original native environment | [137540482204](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165645/job/137540482204) | first-full.zip, first-full.json, verify_first_full.py |
| Same c6a native files with portable binding | [137545834499](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130876742/job/137545834499) | same-native-full.zip, same-native-full.json, verify_full.py |
| Next integrated source e3277e96 | [Original startup workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787247) | Separate source-specific build and run |

The local six-case comparison separately recorded five child-lookup failures changing to five passes. The local codex case reached the Unix socket setup, where the local runner refused the socket operation. Its actual hosted result is present in both hosted ZIPs.

Run from this directory

```sh
python verify_first_full.py
python verify_full.py same-native-full.zip --source c6a3ed9c36f88707d2f29630efe1e3ea4ee0e902 --digest 7c3e46a80e1ba45954cd9bbba5b0add4d72adeed6b06f6b1ec5f52f363fa54e9
```
