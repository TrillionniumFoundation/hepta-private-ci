# Conversation image phase observations

The retained large-image integration failure completed its MCP tool call before
the original event wait expired. The later model request contained the expected
1920 by 1280 high-detail image derived from the original 3000 by 2000 RGBA input.
Those bytes do not identify which part of preparation or history recording used
the intervening time, and do not make the timed-out test a success.

This diagnostic adds fixed trace events at existing boundaries. It uses the
existing `record_conversation_items` span and existing parent spans; it creates
no new span or subscriber. New fields contain only a static phase label, an
image count, or elapsed milliseconds from `std::time::Instant`. They contain no
image bytes, URL, path, prompt, credentials, or additional identifiers.

| Phase | Meaning |
| --- | --- |
| `prepare_begin`, `prepare_complete` | Entire existing synchronous preparation, including cloning, image/audio preparation, stamping, and item IDs. These events also occur for batches with no images. |
| `image_load_begin`, `image_load_ready` or `image_load_error` | One existing `load_data_url_for_prompt` call and its original result, before the same `?` propagation. This covers cache lookup and any processing the callee performs. |
| `state_lock_wait_begin`, `state_lock_acquired` | Before and after the existing state lock acquisition, only when successful image preparation produced metadata. |
| `history_recorded` | After the original history-recording block and release of its state guard. |
| `record_complete` | Return from the existing recording sequence, including its existing persistence and notification calls. This is not proof of durable storage success. |

The four recording phases use one cumulative monotonic origin immediately
before the original lock wait. `image_count` is the successful preparation
metadata count, not a cache counter or a unique-image identifier. The acquired
event runs inside the original guard. Logging overhead is therefore included;
these observations do not measure exclusive CPU time or provide a zero-overhead
lock measurement. Missing end events do not identify a cause. Existing parent
span fields are unchanged. The callee has no duplicate phase instrumentation.

No new await, dependency, task, lock scope, retry, image mode, codec, dimensions,
detail, return value, assertion, or deadline is introduced. The two source edits
remain at the actual boundaries so the original operation order and guard scope
can be checked directly. The integration fixture and image-processing utility
remain unchanged. Only formatting and source checks have run for this candidate;
the next normal source-bound integration run must provide actual phase evidence.
This diagnostic does not claim that the timeout has been fixed.
