# Exact 57b source repair evidence

The published source is `57b27c81d0d5321b873ee751fd0e58e1d905b988`. Its complete source gate naturally failed: 482 cases, 38 failures and 2 errors (442 observed passes), without timeout or inventory changes. The complete original failure log and result are preserved here.

This repair changes 17 source QA files and three exact `product_callers` lists. The two extra QA files were already passing but depend on the corrected owner-channel caller list. All 147 existing affected case names remain. The two moved attack markers now target the actual delegated read-only helper and both original Root signature-reading paths. The old unregistered-caller and mutation attacks remain.

The three registry omissions are actual calls in unchanged 57b Rust: the Trainer readback service constructs the original bounded owner channel; the Evaluator Trainer-readback factory reads its original receipt profile and consumes it through the existing host constructor. Each old row fails on that source, the exact added registration passes, and deletion or an unregistered copy is still rejected. All 607 boundaries, 425 protected rows including duplicates, forbidden lists, other fields and both original scanners remain unchanged.

The combined 17-suite run passed 147/147 in 75.2168 seconds, with all 293 physical inputs unchanged. This is a scoped local source check, not a complete repository source gate, native test, complete caller proof, ordinary launcher qualification, or deployment. The four ordinary qualification counts remain zero. Later Rust compiler diagnostics and their repair are a separate candidate, not included here.

## Packaging

The full 1.8 MB before/after registry texts are losslessly gzip-compressed with logical identities in MANIFEST and registry proof. The 17 final QA postimages and exact 18-path patch are included; all 18 strict replay outputs match their recorded bytes. Rust source copies are intentionally omitted. Actual typed/free-call evidence includes exact source path, SHA, Git blob and relevant call excerpts; fetch the unchanged source from the pinned published commit to rerun against a full tree.

Local preparation errors caused by missing overlay dependencies are retained as attempts 01/02; attempt 03 reproduced the eight-suite 13 original failures without setup errors. Candidate before/after-01 preserve the remaining original failures and the independently discovered missing registry edge. No failed original has been replaced by a passing result.
