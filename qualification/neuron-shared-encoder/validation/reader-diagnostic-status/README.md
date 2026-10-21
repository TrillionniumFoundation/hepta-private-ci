# Reader diagnostic execution status

This isolated child applies to owner commit ca2768978429a2c9a98641fa2d58a8f587b88874. The report producer now distinguishes completed execution from compliance with its existing evidence-answer contract. Full/injection rows require the registered gold answer; other control rows require UNKNOWN. Predictions, model calls, CLI exit behavior, workflow triggers, and the provenance adapter are unchanged.

The exact historical report has 64 completed calls and 38 evidence-contract violations. Its bytes remain unchanged in tests/fixtures and its SHA256 is asserted by the regression test. The second test uses four explicitly synthetic compliant rows and an incomplete subset. Even a compliant diagnostic report remains qualification_status=not_qualified; these tests do not establish independent holdout, semantic review, or physical cost.

The existing owner workflow discovers test_*.py under qualification/neuron-shared-encoder/tests, so no workflow change is needed. The publication validation ran both new tests through that discovery command in this minimal bundle. It did not run the complete owner suite.

The original review receipt and cost reconciliation are preserved. PUBLICATION_RECEIPT records only the repository-relative test/fixture relocation and its validation.
