# Windows Fleet creation candidate

The exact e516 source and its actual checkout merge have the same tree. Its original Agentd Windows library ran 172 distinct tests in three batches: 167 passed and five failed when the strict cognitive owner rejected the directory owner or DACL. The complete original job log is retained.

The initial three fixture-only proposals are retained under `rejected-fixture-only/`. They were not adopted or executed. They would create legitimate test leaves while leaving the same incompatibility in real Fleet registration. No claim that these fixtures fix production is made.

The eight files under `source/` are the reviewed-scope candidate, based on exact union source 0cf81d. They introduce an exclusive private-directory creator using the existing native no-reparse acquisition and explicit current-user descriptor; Fleet uses it only for initial private-directory creation. Existing object ownership and ACLs are never repaired. Original Agentd fixtures, assertions, timeouts, negative controls and ignore policy are unchanged.

Three original test files retain all their prior bytes and append four Windows cases: real production registration validates all nine owned directories below an ordinary parent; duplicate creation refuses existing private state without changing its descriptor or payload; restricted existing state is not repaired; a junction cannot redirect new creation. The sole new local dependency edge is Windows Fleet to path-utils.

These source bytes have been stored and read back exactly. No current-candidate compiler, formatter, native test or Bazel gate has executed here. The complete composed source must undergo actual Cargo and Bazel generation, original path-utils/Fleet/Agentd tests and existing negative gates. New inventory is discovered from compiled tests; no fixed count is lowered. Windows filesystem durability beyond the existing adapter is not established.
