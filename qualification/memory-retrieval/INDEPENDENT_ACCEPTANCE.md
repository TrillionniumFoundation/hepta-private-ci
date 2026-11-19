# Memory retrieval independent acceptance

No independent acceptance is recorded by this file. It defines the required evidence and signer separation.

Promotion of `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation` or `release` from false to true must occur in a non-draft pull request and receive an approval on the exact current head from a repository owner, member or collaborator other than the pull-request author. Superseded approvals, bot reviews, comments and CODEOWNERS routing do not count.

The reviewer must inspect semantic tests, exact-source and deterministic synthetic-merge receipts, provider lease/rotation/revocation/recovery tests, vector-owner evidence, end-to-end SLO receipts, threat controls, canary results and rollback rehearsal. Approval of source integration is not deployment or release authority. The automated gate is `scripts/verify_memory_retrieval_review.py`; its receipt records the promoted fields and qualifying reviewer identities without converting that approval into runtime authority.
