# Serialize first initialization of V8's sandboxed backing allocator

Base: `5756a7a47269abfb2a1e84c70b59d7ac5cdb6be6`.

The complete original Windows MSVC shard 3 job `140594591682` (run `46025167575`) aborted all three V8 targets at `partition_address_space.cc(301)`, with `!IsConfigurablePoolInitialized()`. The complete raw log is retained here as gzip; the original matrix remains failed.

The pinned V8 source `15.0.245.2` has this first-use chain:

- `src/api/api.cc`: `ArrayBuffer::Allocator::NewDefaultAllocator` constructs a wrapper whose constructor calls the default isolate group's shared backing allocator.
- `src/init/isolate-group.cc`: `GetSandboxedArrayBufferAllocator` calls `LazyInitialize`; its `if (impl_) return;` and `make_unique<Impl>` have no synchronization.
- The PA-backed `Impl` creates the process-wide configurable pool, which permits one initialization.
- Rusty V8 `v150.4.0/src/isolate_create_params.rs` requests a default allocator in `CreateParams::finalize` when one was not supplied.

The existing application and proof-of-concept V8 once guards already serialize V8 platform initialization. This change constructs and drops one default allocator wrapper inside that same guard, before it releases any concurrent isolate constructors. The shared backing allocator remains owned by the V8 isolate group; dropping the wrapper does not reset it.

The original six proof-of-concept test functions and their assertions are unchanged. Runtime/host test definitions, original timeouts, concurrency, sandbox feature, V8 version, native archive integrity and dependencies are unchanged. No global test serialization or retry is added.

The dedicated workflow runs the same three full original Windows targets with uncached test results. It requires explicit PASSED lines for all three and refuses any failed/retried attempt or FLAKY result. This is a targeted qualification; the complete platform matrix remains independent. At this source commit the Windows result is PENDING.
