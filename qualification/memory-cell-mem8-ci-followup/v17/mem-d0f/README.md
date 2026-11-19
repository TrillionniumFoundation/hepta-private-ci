# Original d0f MEM workflow evidence

Source d0f6507e08f7f5c5855f5164d07c049a34d1a6d9, tree 658fa040046285116b1fd81b94ff8c96444072ad. Original run 43062473099, attempt 1, all three jobs completed successfully. No retry or successor execution was created to collect this evidence.

The original Python work produced 154 executions and 120 distinct case names: integrity 35, CPU 119, with 34 overlapping names. Native fixture work produced 34 executions and 33 distinct case names: memory 11, Agentd 6, the same profile case again under qualification-cognitive-write 1, protocol 16. Three drain child markers are inside one selected Agentd case and are not extra selected tests.

The native artifact retains all 10 command receipts and raw logs, exact current source identities, three fresh JUnit files, unchanged observed CLI bindings, all 224 archived source-before files, and empty source-after/rewrite captures. The memory JUnit was replaced by later nextest runs; its exact cases are proved by its original raw log and command receipt. The large CLI executable is not archived; only its original build and observed before/after byte hashes are retained.

This package includes all three original ZIP artifacts, original fulljob logs, API terminal metadata, full Git tree inventory, and deterministic offline readers. Run `python3 verify_mem_package.py MEM_D0F_ORIGINAL.tar.xz` to verify every outer member, all original ZIP members, raw/receipt/case/JUnit/source bindings, and regenerate the four final audits byte for byte. This runs the evidence readers only; it does not run repository code, build, tests, models, or recorded commands.

The synthetic 14-reader-process campaign remains a software memory-path check with zero model calls. These results establish neither new scored actor benefit nor original owner recovery, an independent trust domain, effect-owner recovery, or overall repository CI acceptance. Architecture is a separate original workflow and is not included in this completed MEM package.
