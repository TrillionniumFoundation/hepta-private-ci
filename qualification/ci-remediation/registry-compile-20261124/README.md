# Durable registry compile and fixture qualification

The source at `676d59ef602e59790a58614541bfb92325bdc71f` failed the architecture source-head job before its supervisor tests: `durable_payloads.rs` used `File` without importing `std::fs::File`. The one-line import restores the existing file type on both platform paths. It does not change payload publication, hashing, ownership, durability, or poisoning behavior.

A local qualification manifest pointed directly at the entire registry library and its existing unit-test source files, with repository contract/type dependencies and the current selected dependency versions. The unchanged existing Linux suite executed **50 tests: 50 passed, zero skipped**. This is a separate 82-package qualification graph, not a full workspace or Windows pass.

A strict Clippy check then found ten existing relation-fixture `expect` calls denied by the workspace lint policy. These calls now use the already-present `TestMust` test helper, which still panics with the error on failed setup. All test assertions are unchanged. After this cleanup, scoped `just fix` and ordinary `just clippy` both exited zero without warnings. The two affected relation tests both executed and passed; 48 unrelated tests were explicitly filtered out in that second run.

The final source hashes were identical before and after qualification. `receipt.json` records source commits, the original failing CI job, exact counts, input hashes, and limitations. The initial full-workspace attempt stopped at an out-of-date lock in the transport checkout; it is retained as a failed attempt and is not counted as compilation or qualification.

Integrated normal CI, native Windows registry tests, and downstream consumer tests remain their own required evidence. No registry assertion, storage guarantee, or production authorization was relaxed by these changes.
