# Original complete source-QA failure at 186eea3f

The exact frozen candidate and source inventory are recorded in `inventory.json` and the unmodified original manifest. Full source-closure discovery ran 327 tests and exited 1 with four failures and no errors. The failures concern existing caller-list expectations after adding real historical-data callers; they are not native test outcomes, a timeout, or four proven runtime defects.

The clean before/after inventory contains 7,483 files and SHA-256 `0bba47af21b2d7432296b8b20b51ccab57505f8c40a91b58b3771e71c92944c6`. The full 75,378-byte log has SHA-256 `30c25f84c18f234ff0ccb61090aff3eaa3225a8f93daccf5e8ff66a178f462ce`. Both complete originals were compressed and verified byte-for-byte after decompression. Later caller-fixture repairs require their own exact-source results.

This scope is source QA only. Complete A-to-C positive, NoUpdate and daemon-plus-Root cold-restart counts remain 0 / 0 / 0.
