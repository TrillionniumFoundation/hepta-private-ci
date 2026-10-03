# Bounded host-fixture and recovery-selector repairs

Exact source `fb7204b139987fa5b047c8fc06ab591bbac35d99` reached a zero-test
`destination_recovery_binding` selection in Agentd run 37105946617, Linux job
111154369359, after 418 library and 17 process tests passed. The replacement
separately selects actual production-writer and cognitive-destination contract
groups. The imported executable shell regression checks the real source inventory,
wrong grant/destination, lost acknowledgement, indeterminate no-redispatch and
exact replay contracts. Each empty group still fails. The existing Codex binary
build and all later gates remain intact; no runtime branch workflow is copied.

The same run's Darwin job 111154369364 passed 394 tests and failed 24. Five failed
before intended behavior at noncanonical temporary paths: four HNMF cases share
one fixture and the run-start case used a noncanonical checkpoint parent. Only
those fixture path constructions are repaired. The 19 supervisor release-install
PermissionDenied cases remain unresolved, outside this change.

Two additional narrow platform hunks reuse published source
`1393f3b2a38fee745006175425571c702bbb28b0`, whose preimages match this branch:

- `cognitive_test_support.rs`: `dbd71ef718ae11c5d4a3568a3f9ed4f381236473`
  to `11306805bca685a18758b50c16659a75092e0077`, canonicalizing the created fleet.
- `.gitattributes`: `29f1c6ddf7d496dffcb3ea4872c449a9f0d3c327`
  to `20fbe6f83f656a5b4a576db7f7e1849845c363e1`, preserving memory SQL LF bytes.

Independent in-memory SQLite execution of this branch's 172 required schema
objects reproduces the actual LF oracle `7b32453fc923029528459c438b35bc9248c6e56edf908016c6bddeeb9077b893`;
CRLF yields `2a5fd3d75f69d3c952981fd1cce25850848f294eba4718622a8afb60aad9cea0`.
An `autocrlf=true` checkout changes bytes before the rule and preserves exact LF
bytes after it. No migration SQL, schema oracle or production admission changes.
This source-level reproduction is not Windows Rust qualification and does not
resolve the separate unsupported Windows secure-registry boundary.

## Separately verified preceding execution

Cognitive run 37105946667 source artifact 11268622287 has ZIP SHA-256
`32b636b5c43478ce558fc056416ac8c246fa22c281878b633389de615592d6fd`, TAR
`100bf58fc232580489f62b41ae54b2574e615934ec2cd8d0fa0cc6a06f4c8d8b`.
Merge artifact 11268796703 has ZIP
`a9be0dc6e9589c65b97749fa0bda4e786d98bf1c0155b1113c21acba0d350002`, TAR
`8b1d128a8caa5a96d6637328d177ffcae638b76ebae982d046b0b57d4764d0ea`.
Each has 194 verified checksum entries and 193 verified receipt entries. Source
fb7204 and merge e13d279529f7f7823f8fa177894abee1d65f3a15 share tree
e88e7c458f4c676180bf553b2e237eb6bed3b9b6; merge parents are recorded base
8145cc3766246263e4acc992ffd6a85a7004a8c6 and source fb7204.

Both executed 287 owner, 226 Agentd and 56 cognitive core tests successfully,
along with actual read/replay, write-smoke and native final-use cases. The locked
fuzz harness and clean-source check passed: the formerly generated untracked
nested lock is no longer a receipt problem. Only strict and compatibility Clippy
fail, each on five paused AuthBus diagnostics. These are prior-source results,
not execution of these new fixture changes. Production implementation, product
execution proved, independent acceptance, activation and release remain false.

## Local validation and limits

The actual recovery-step shell regression is red before the selector change and
green afterwards. Focused Python and source-identity results are retained beside
this record. New-source owner/process Rust tests await hosted execution; no broad
local build or shared-cache restoration was performed. The workspace Cargo.lock,
paused AuthBus/state files, registrar/publication and authority checks are unchanged.
