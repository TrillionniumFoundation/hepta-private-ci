# Actual final holdout physical-refusal tests

Clean source 8b83dbc8 ran the original locked-file CAS test group with `just test`, zero retries and `--no-tests fail`: all nine cases passed, zero skipped. This includes four new actual-file negative controls and the five existing lock/replay/recovery cases. The raw nextest log, exact JUnit, before/after identity, command, environment, source QA output and three-commit source bundle are retained without rewriting the observations.

Each corruption sequence asserts a successful original observation, the first refusal while bytes are corrupt, and a second refusal after the original bytes are restored. The idempotent-CAS path is also physically checked before its early success return. Reads replay the existing frame grammar and minimum witnessed cut; successful writes are synced and physically replayed before the cached state changes.

These results establish same-handle refusal for this implementation and test scope. They do not establish cross-process permanent refusal: one test explicitly drops the poisoned owner and successfully reopens restored valid bytes using the retained cut. The cached anchor getter remains data, not a physical-current proof. Independent B custody, scientific evaluation and the ordinary full chain were not qualified by these tests. Complete positive, NoUpdate and daemon plus Root cold restart counts remain zero.

The eight new source-closure cases passed on this exact source. No complete caller scan is claimed. A separate sibling performed a source review; it is not a second native run.
