# Ordinary V4 execution-source CLI repair

The selected remote base is `c809b4cec93bd7daa64c2bfe0a2d7af5c886f2b9`.
The unchanged V4 manifest pins Chain
`c16507147b65285ea94dead22d3b93c5db7295af`.

The public material entry point had a separate argument-parser list containing
V1–V3. Consequently an explicit V4 invocation failed at argument parsing even
though the execution-source verifier already supported V4. The two CLIs now
use one closed profile registry, and the original manifest, commit, path,
hash, dependency-closure and pre-download checks still execute.

The new regression launches the real public script in isolated Python processes
with real argv for every registered profile. An unqualified checkout must reach
the exact-source refusal before download or output creation. A separate
forwarding regression retains the historical no-profile behavior.

The continuation CI selectors explicitly recognize the new repair branch.
They retain the c165 source pair, complete effect recovery and 77-test SQL
minimum. The model workflows collect the two added V4 tests.

`checks.json` binds the modified source files to the newly executed commands.
The earlier 40-test baseline and 42-test changed-source logs are retained
separately. They are component controls on a sparse source copy, not a complete
native build, recovery or model run. GitHub publication uses the real remote
base tree and verifies each original edited blob; the local sparse snapshot
commit is never represented as that remote identity.

This repair does not change the selected Chain to the separately developing
system/PQ composition. That combination still needs a new immutable source
profile and fresh ordinary-entry, build, recovery, model and budget acceptance.
No three-round training/installation result, independent WAN acceptance,
production activation or whole-chain post-quantum qualification is claimed.
