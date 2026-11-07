# ZIP permission fixture compatibility

The updated ZIP API returns a sanitized `unix_mode()`. Source leaf
`12a4c2e3487476b54fc28e4fa3109604c498f566` checks the original raw external
attributes for the fixture's pre-extraction SUID/SGID/sticky bits. The original
production extraction and its resulting permission assertions remain in place.

The [publication manifest](publication.json) preserves the original failed
precondition, its successful corrected run, and the complete original420/420
owning-package result with zero skips. Scoped fix also replaced two existing
closures with equivalent method references, then formatting passed. The strict
one-file driver guard stopped on those extra mechanical edits; its failure is
retained alongside the reviewed final diff. Final post-format bytes were not
retested in this phase. This scoped result is not a full composed-workspace pass.
