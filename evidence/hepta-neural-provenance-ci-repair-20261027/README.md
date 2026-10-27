# Actual first-run compile failure and bounded repair

Source `6e5127ec2d128956b1770a64fd97ade6eb59426a`, run `40494601404`, job `122156744033` failed. The archived records preserve the original E0432 diagnostic: the new Agentd test imported `pretty_assertions` without a declared crate dependency. The CLI built, but **zero tests executed** and every real-model step was skipped. The target detector found no executable; the required-outcomes gate correctly rejected the skipped execution.

The repair uses Agentd's existing standard `assert_eq!`, with no dependency change. The new execution payload is boxed internally to address the observed large-enum warning; the protocol test compares its complete JSON object and decoded payload, preserving the wire schema. Two existing ranker identity conversions and two test-format suggestions are corrected from the actual Rust 1.96 Clippy output.

`failed-run-records.zip` is the complete 32,769-byte original records artifact, SHA256 `364419e8c9afef6e5cfeedf4c45e7ea0b884df9bade8dd7588d90000ebe86fb9`. It contains build/test diagnostics and source observations, with no model execution, issuer material, private keys, or user credentials. `repair-observations.json` records the local command attempts. The local host lacks `just`; Rust 1.95 formatting is only a syntax precheck. New exact-source Rust 1.96 CI must execute the original four-package and actual-model lanes before success can be claimed.

No workflow condition, target detector, model budget, current selection, installation qualification, or authority gate is changed. The earlier f75 `RuntimeOpen(StateLocked)` restart failure remains a separate unresolved lifecycle issue. These compile/lint changes do not prove a model benefit, ordinary upgrade, or production qualification.
