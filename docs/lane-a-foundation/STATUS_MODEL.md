# Lane A orthogonal status model

Every module reports six independent axes. No axis implies another.

| Axis | Question |
| --- | --- |
| `source` | Does a bounded native source root exist? |
| `implementation` | What implementation class exists now? |
| `durability` | What state survives process and host failure? |
| `qualification` | What exact class of tests/evidence exists? |
| `activation` | Is there a named product caller and enabled path? |
| `acceptance` | Has an independent authority accepted the exact candidate? |

The following implications are forbidden:

- `source=implemented` does not imply a production caller;
- `qualification=*tests_present` does not imply acceptance;
- a target API in a dossier does not imply a native symbol;
- an in-memory model does not imply durable recovery;
- a nonzero signature digest does not imply signature verification;
- evidence persistence does not grant promotion or release authority;
- external secret metadata does not transfer ownership of secret values.

A module may advance one axis only when the corresponding exact-candidate
receipt exists. Rollback, migration and retirement decisions must name the axis
being changed rather than using an overloaded word such as `complete`.
