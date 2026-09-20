# Lane A orthogonal status model

Every module reports six independent axes. No axis implies another.

| Axis | Question |
| --- | --- |
| `source` | Does a bounded native source root exist? |
| `implementation` | What implementation class exists now? |
| `durability` | What state survives process and host failure? |
| `qualification` | What exact class of tests/evidence exists? |
| `activation` | Is there a named enabled product caller? |
| `acceptance` | Has an independent authority accepted the exact candidate? |

A module may advance one axis only when the corresponding exact-candidate
evidence exists. Rollback, migration and retirement decisions must name the
axis being changed rather than using an overloaded word such as `complete`.

The matrix also records lane-level closure fields. In particular,
`targetArchitectureImplementation=partial` is compatible with
`repositoryControlledDocumentationGaps=closed`: the first describes future
implementation, while the second describes the checked-in documentation and
traceability obligation.
