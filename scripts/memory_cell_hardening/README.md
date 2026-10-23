# Memory admission hardening

This follow-up preserves the earlier local experiment and adds two bounded
admission guarantees around existing research interfaces.

`ParametricOwner.invoke` now re-observes the supplied withdrawal frontier and
checks the active version after checkpoint-byte validation, immediately before
calling the model consumer. Its final short SQLite transaction is the local
admission linearization point. A withdrawal or version update committed during
the potentially expensive validation stage therefore prevents the callback.
No database transaction spans the callback; callbacks may still invoke an
independent owner. Changes after admission may overlap an in-flight callback,
whose result is then suppressed by the existing post-callback checks. This does
not promise an atomic relationship with an external source authority.

`tensor_contract.bounded_read` now requires a bounded regular file before open,
checks descriptor identity and type, and rejects observed size or timestamp
changes during the read. Where available, `O_NOFOLLOW` and `O_NONBLOCK` prevent
symlink replacement and FIFO blocking during open. Platforms without those flags
retain pre/post-open checks without an atomic no-follow claim. Independently
retained content hashes remain required by the caller.

The focused tests use actual SQLite owners, safetensor files, ordinary filesystem
mutations and POSIX FIFO probes confined to child processes with timeouts:

```bash
PYTHONPATH=scripts/memory_cell:scripts/memory_cell_hardening \
  python -B -m unittest discover -s scripts/memory_cell_hardening -p 'test_*.py' -v
```

The earlier zero-callback withdrawal observation concerns roots already revoked
at request entry. This follow-up strengthens pre-callback admission without
retroactively expanding that observation into a concurrency guarantee. Source
authority remains a trusted host input; production acceptance stays false.
