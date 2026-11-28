# Capturing an existing SDK turn

This POSIX-only producer reads one caller-authorized thread through the existing
Python SDK and retains the observable subset of one explicitly selected completed
turn. It does not start, resume, steer, rename, or interrupt a thread or register a
notification consumer. The SDK must be installed from this repository's compatible
Python package. The command starts the normal SDK stdio app-server and initializes
that connection; it does not submit a model turn or change login/configuration.

From the repository root, after selecting an existing thread and completed turn:

```sh
PYTHONPATH=scripts python3 -m cell_experiments.sdk_capture \
  --thread-id EXISTING_THREAD_ID --turn-id COMPLETED_TURN_ID \
  --originals /absolute/private/materials/originals
```

The parent of `originals` must already exist. `--codex-bin` optionally selects the
caller's installed runtime. An application that already owns an `AsyncThread`
can instead await `capture_completed_turn(thread, turn_id=..., originals=...)`.
Both callers execute the real `await thread.read(include_turns=True)` method. The
SDK reads the entire specified thread history; the caller must already have
permission for that read. Only the selected turn's permitted fields are retained.
There is no passive second `AsyncTurnHandle.stream()` subscription: existing turn
streams consume a shared queue and a second consumer would steal events.

## Frozen source contract

`hepta.sdk-observed-turn-source.v1` preserves SDK-reported thread/session/turn/item
IDs, item order through original indices, and typed payloads for `userMessage`,
`agentMessage`, `commandExecution`, `fileChange`, `mcpToolCall`, and
`dynamicToolCall`. Other item types retain only ID/type/index omission metadata.
Reasoning content and summaries, hook prompts, and other turns are excluded.
References to files, images, and URLs are copied as reported; they are not opened.
An absent/null agent-message phase stays unknown, not an inferred final answer.

The source is Pydantic's known typed fields serialized with JSON mode, aliases,
and `exclude_unset=True`, followed by sorted, compact, finite-only UTF-8 JSON.
It is not the original JSON-RPC bytes. Both `raw_wire_preserved` and
`source_signed` are false. A defaulted `itemsView=full` is distinguished from an
explicit field; neither proves original-history completeness. Provider/version
strings remain reported metadata. Teacher opaque identity and model SHA are
unknown, and completion/tool status is not a correctness or execution proof.

Bounds are 256 returned items, 256 characters per identity, and 1,048,576 output
bytes. Wrong threads, missing/duplicate selected turns, incomplete turns, non-full
item views, duplicate item identities, and oversized sources are refused. Content
is never truncated to fit. These bounds apply after the SDK's history read and
are not transport, memory, hard real-time, or remote-filesystem bounds.

## Create-only original slot and remaining inputs

The raw bytes are stored at `originals/<sha256(raw)>`. This is the actual slot
hashed by `paired_source.check_attempt` and `capture_attempt` through
`coding_sft.file_hash`. It satisfies only their source-byte prerequisite. It is a
distinct schema, not `hepta.cell-experiments.record.v1`, and is never passed to
either consumer by this producer.

Every path component is opened without following symlinks. The final directory
must belong to the current effective UID with mode 0700. A new source is written
and fsynced as mode 0600, then hard-linked into the digest slot without replacing
anything. An existing digest slot must be an owned private regular file with the
same length, exact bytes, and stable metadata across readback. FIFO, directory,
symlink, changed-byte, and permissive-mode slots are refused. No existing path is
chmodded or overwritten. Directory descriptors prevent parent-path redirection
during publication; this is not authentication against another process with the
same UID. Later consumers still need their own read/hash/authority checks.
Existing-file equality does not certify crash durability for bytes written by
another producer; only the newly staged file is data-fsynced by this operation.
The file write runs in a worker thread; cancellation can leave a complete source
already published. A failed publication attempt never creates a training record.

The command prints only source identity/size, original thread/turn IDs, and
whether the file was newly created. Keep this directory and its content private.
No current user data or teacher credentials accompany this slice, so validation
uses typed engineering fixtures without launching a runtime or making teacher
requests. These controls do not demonstrate live capture or training.

To enter the original training path, separate original task/verifier metadata,
policy/model identity, rights/Train consent, actual material and outcome receipts,
and original Core/AuthBus/Root owners are still required. An SDK client ID is not
an original verified Train turn. This producer creates no enrollment, study,
semantic label, evaluator signature, useful-work credit, or training request.
The fixed paired-enrollment protocol is not an unlimited online-training stream.
