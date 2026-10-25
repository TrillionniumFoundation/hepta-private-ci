# Original fleet and restart durability scope

Product source `7a166d9b809c98230bb5bbabe2281aaa70e58610` preserves the original
merged main/companion restart record. Each unchanged write freshly reads and
validates the complete canonical bytes, binds its regular private descriptor,
and synchronizes that same file and its parent before ACK. It uses no cross-tick
cache. Actual changes and legacy migration still use the original publication.
The original restart scope passed 21/21, including real descriptor/symlink and
rename-before-directory-sync failure cases. Final product blobs match the tested
source, scoped fix and formatting passed without changes.

Fixture source `611f7519dce52afacc63eef127f98d405bcd8398` starts independent real
agents and creates independent peer threads in groups of two. Every original
readiness/identity check completes, IDs retain input order, and both real thread
requests and shutdowns finish before advancing. The original model responses,
mutations, cleanup, assertions and duration expressions remain unchanged.
The four original cases passed in 19.046s, 20.741s, 12.448s and 12.513s under their
original 60-second limits, sequential nextest execution and zero retries. The
preliminary failing candidate remains a failure; these results belong to the
final source assembly. Product timing instrumentation was excluded.

[Ten original qualification, test, fix and format records](publication.json)
retain exact source blob and raw log hashes. Rust 1.95/dev-small scope success is
not a full 1068-test aggregate or final Rust1.96 workspace result. The writer256
and supervisord cases, production writer and G2 remain separate open work.
