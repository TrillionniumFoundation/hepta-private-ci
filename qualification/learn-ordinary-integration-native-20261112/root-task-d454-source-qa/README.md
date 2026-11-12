# Original Root complete-task source QA failure

This is the exact failed source-QA run for local candidate `d454997a75bd1cce2b09b52940b4a71ee987d84c`, tree `675cfb8694d4c74eb9b2e0790c0e5c6804a97db4`. It ran the full `qa/b4-no-bypass/*source_closure.py` unittest discovery command recorded in the original manifest. The command exited 1 normally. Its wall-clock interval was 61.718 seconds; unittest reports 299 tests in 59.025 seconds, with **12 failures and 3 errors**, including subtests. These counts are not used to infer a separate number of passed tests.

The raw log identifies conservative receiver-resolution errors for the borrowed original RunStart reader and the Ledger `RootDataRefusalV1::inspect` receiver, plus existing caller-fixture expectations affected by the newly connected cold-data caller. Several negative controls fail because the unresolved-receiver error occurs before their expected caller-set rejection. The full log is retained so these are not misrepresented as 15 independent runtime defects or as a timeout.

Before and after source inventories are identical and clean: 7,461 files, SHA-256 `e762f0b63efec752fc13954ac21a9791da021c02ca72beca3311b0fe28a57c29`. The 96,441-byte log has SHA-256 `6b7643c27de223993145470b1ad9cb0ff184aeb92d0fe0e3de442196da334666`. Both original files are stored without transformation in the archive and were verified byte-for-byte after decompression. This record contains no native test execution or full caller PASS. Later explicit receiver/caller-fixture repairs require separate source identities and observations.

Complete A-to-C positive, NoUpdate and daemon-plus-Root cold-restart qualifications remain 0 / 0 / 0.
