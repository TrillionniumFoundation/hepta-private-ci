# V42: exact Factory receivers after the original V41 caller failure

This candidate replaces five implicit calls with the same actual `AgentdRootQ24ModelFactoryV1::require_current` mutable receiver. The original Factory implementation, Stage and Context boundaries, all caller sets, Gate, 500 ms request budget and failure behavior are unchanged. Only corresponding source spellings in one existing protected row and the exact CALLERS digest are updated.

V41 on `b399a82f5bbf53fe270e477bd90ccd2cdedcdebf` completed with exit 1 after 236/236 QA and caller self-test passed. Full caller verification failed on an unresolved possible Stage receiver. Ordinary seven-package native and Root17 were not reached. Full terminal is complete, maintenance patch is empty, and all five original cleanup checks passed with clean source.

The included review is static and bounded. V42 must receive a new run of the unchanged complete original harness at its own source; no V41 qualification is inherited. The future B, Session, Circuit, Root retirement and daemon entry slices are not installed by this candidate.

Ordinary complete / positive adoption / genuine NoUpdate-or-rollback counts remain **0 / 0 / 0**. Independent C consumption and physical daemon plus Root stop/restart remain unaccepted. Draft only; no main merge.
