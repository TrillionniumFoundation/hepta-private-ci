# Actual Windows integrity and parent-delete observations

The complete original sandbox target executed at dcdcf94. Its unchanged two
refusal cases still fail; all 149 passing tests and the two pre-existing ConPTY
ignores are retained. The diagnostic executed all 20 mode/route combinations.
No original test was filtered, retried, replaced, or counted as passing.

The raw job and complete artifact are retained and byte-verified. Each of the
20 JSON observations was extracted from that original raw stream. Low integrity
preserved external reads and blocked deletion through ordinary Medium parents.
A different Low workspace still allowed deletion. Adding a FILE_DELETE_CHILD
deny to the Low parents preserved the active capability's own writes/deletes and
rejected writes/deletes through the other capability in this measured fixture.

This is diagnostic evidence. No production token or ACL implementation changed.
Arbitrary pre-existing Low directories, protected descendants and reparse paths
remain required design boundaries. Neither the original permission gate nor
whole Windows qualification is passed by this evidence.
