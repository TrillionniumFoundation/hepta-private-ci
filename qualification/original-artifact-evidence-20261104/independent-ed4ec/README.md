# Original protocol and Windows process evidence

The independent readonly workflow at `ed4ec11a6609f0b8a9e25d6a1c49369c57cef894` completed all three artifact checks in run `41776616025`. All ZIP bytes, CRCs, original Git source bytes and recorded output hashes were checked without executing archived source.

Protocol source `ee24895753b65e5b7cf0ec01398995af2fbfe0f2` has 10,326 original Git inputs: 9,342 non-schema inputs and 984 original schema files. Its original complete library lists 304 cases: 303 runnable cases passed exactly once and the existing fixture-writing helper remains ignored. There are no new skips or retries. All 14 original commands exited zero, all 37 output files are bound, and the three generated files match the recorded Git blob and SHA256 identities. The other 981 schema files are unchanged.

Windows process source `4db82e9ced0af3d2efd2a6c61a5c3da14b5d6f37` passed the original Git 33, Queue 35 and selected idle completion 3 cases. Its original merge `9149d3e01bcc3777b605920cef6bbb166bacf61c` still failed two Git child-readiness cases, while Queue 35 and the three completion controls passed. Both original snapshots contain 9,118 exact inputs with identical before/after hashes. The failed merge remains a blocker. Generic process evidence reports original case observations; the schema reader additionally compares the full compiled inventory with fresh JUnit itself.

`PROVENANCE.json` records original and readonly artifacts, exact log bytes, compact report paths and full report hashes. The process fixture owner independently reconstructed and retained the six small original test logs. Original ZIPs remain available through their immutable artifact identities. No product ref or production admission was changed.
