# Synchronous image loading checkpoints

## Observed gap

An existing GNU integration attempt failed the original ten-second event wait.
Its image-loading interval was 12,000.692478 ms, while the later session-state
lock acquisition was 0.038137 ms. The tool had already returned successfully.
The two other original attempts list the image test as passing. These are wall
times, not image-stage CPU measurements or evidence that any one codec dominates.

The original integration fixture remains a 3000 by 2000 RGBA PNG, expecting a
1920 by 1280 high-detail result. Its inputs, assertions, waits and retries are
unchanged. This candidate adds observations; it does not fix or qualify the
timeout.

## Checkpoints

The caller uses its existing monotonic load clock and trace span. A synchronous
observer reports only a fixed phase label and cumulative elapsed milliseconds.
No image bytes, paths, prompt text, URLs, dimensions or credentials are logged.

| Checkpoint | Work completed since the preceding checkpoint |
| --- | --- |
| `image_data_url_decoded` | Data-URL checks, base64 decoding and the existing size checks |
| `image_cache_hit` / `image_cache_miss` | Path allocation, SHA-1, lazy cache initialization if needed, lookup and its existing lock; a hit also clones the cached result |
| `image_pixels_decoded` | Format detection, decoder creation, metadata extraction and pixel decoding |
| `image_resize_finished` | The existing dimension calculation and Triangle resize, if needed |
| `image_output_encoded` / `image_original_bytes_ready` | The existing encoding or original-byte path, including construction of the returned image |
| `image_cache_store_finished` | The existing clone, cache insertion attempt and eviction operation have returned |

A cache hit emits two checkpoints. An uncached success emits six. Errors emit
only checkpoints reached before the original error; the existing outer error
event remains. Cache-store completion is not a claim that an entry was retained:
the cache still depends on an active runtime and retains its original byte cap.
Resize completion does not imply that resizing was necessary.

Callbacks run after each cache operation returns, outside its guard. The old
public entry points use a no-op observer. The data-URL parser, image metadata,
resizing algorithm, output codec, error objects, cache keys and capacity are
unchanged. There is no new await, task, thread, dependency, global subscriber,
deadline or retry. The final base64 conversion to the outgoing data URL remains
outside this loader, as before.

The elapsed differences include scheduler effects and observer overhead. They do
not measure CPU, decode internals, durable persistence or lock wait in isolation.
Trace output may be filtered or truncated; a missing checkpoint alone is not a
proof that a phase was never reached.

## Source controls and qualification

Three new Rust tests use a private cache and small generated PNGs: resize plus a
subsequent cache hit must preserve all output fields and bytes; original-byte
loading without a runtime must retain the original bytes and disabled-cache
behavior; invalid data URLs and invalid image bytes must preserve the error and
omit later completion checkpoints. The pre-existing image tests are unchanged.

These tests are authored but have not been compiled or executed in this source
review. Formatting, spelling, source provenance and inverse-patch checks are
separate static evidence. The unchanged full image integration test and these
controls require actual qualification on the resulting source before any claim
of native success.
