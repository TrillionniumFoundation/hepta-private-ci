# Frozen ordinary source gates and narrow repairs

Original source: `32a7d4df970cbcae301068eef563bf7ed83c4e73`, tree `cada36795e78c206d6356e532fbba9dfb485d6bd`. Both original complete Python commands ran sequentially, without retries, selected boundaries, changed limits, or source edits. Full tracked-source snapshots were identical before and after each command.

* All `qa/b4-no-bypass/test_*.py`: 909 tests, 9 failures and 4 errors, exit 1. Subtests make subtraction an invalid unique PASS count.
* Complete `verify_hepta_callers.py verify --root`: exit 1 after 210.9916 seconds. The first actual failure is the missing `authority_host_publication_acceptance.rs` caller of `root_generation_current_original_broker_head`. This is a caller failure, not a timeout.

The compressed archives preserve the original stdout, stderr, commands, full source hashes, terminal metadata and driver bytes. Every archive member was decompressed and compared byte for byte with its original. The original files remain retained locally as well.

Separate repair `39086bfa56df811acee1c0b04df88a5ff6ed405f` changes only seven static QA caller dictionaries to match the actual production callers. The seven complete files ran 68 tests with exit 0; source stayed unchanged. An AST comparison confirms that all other test and negative-control logic is unchanged. Sticky owns the independent B-routes fixture correction.

The second repair `33a5a338637a4787237bc4154b23a06f6ad34357` adds only the actual acceptance caller to the one manifest row and the existing historical-capture fixture, including an unregistered-caller negative. Its complete caller CLI is a separate run, still pending when this evidence bundle was made. It does not inherit a full-source PASS.

No Rust or native test was executed by these gates. Whole Adopt, evaluated post-B NoUpdate and daemon-plus-Root cold recovery remain 0 / 0 / 0.
