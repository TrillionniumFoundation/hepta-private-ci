# Private Linux X11 desktop input Organ

The original `ProductionDurableWriter` owns preparation, FinalUse, dispatch and
terminal persistence for topic `trill.desktop.input.v1`. This adapter adds no
issuer, operation database, retry queue or independent success publisher. Its
terminal `Committed` state means **X11 server input injected**, not completion of
the third-party application's business action. An independent screenshot is an
observation and is never accepted as terminal evidence.

## Ownership and implementation

- `hepta-memory/src/production_desktop.rs` reconstructs the original operation
  intent, binds exact payload bytes, and enters the effect channel synchronously
  inside the existing FinalUse consumer. The returned future cannot defer input.
- `production_private_organ.rs`, the original writer and local outbox require the
  matching complete typed receipt for Notes and desktop topics. Generic apply,
  reject, reconcile or rollback cannot invent an input terminal result. Original
  pre-dispatch authority rejection retains its nonserializable no-entry proof.
- `hepta-agentd/src/desktop_bootstrap.rs` accepts two explicitly inherited unnamed
  AF_UNIX streams. `desktop_channel.rs` keeps effect and observation capabilities
  separate, bounds the entire exchange to two seconds, verifies correlation and
  closes an uncertain stream permanently. There is no reconnect or replay.
- The original `attach_production_operation_host`/`attach_target` composition is
  used with `ProductionDesktopTarget`; the launcher must still supply all real
  production authority inputs. Receiving a descriptor ACK does not install or
  fabricate any of those inputs.

## Exact contract

The immutable cross-repository fixture is
`tests/fixtures/desktop-x11-v1.json`. Its raw JSON strings are intentional: payload
and receipt digests cover those exact UTF-8 bytes, not normalized JSON.

The target identity is `(session_instance, incarnation, display_epoch)`, each 32
lowercase hexadecimal characters. Its destination is
`trill.desktop:{session_instance}:{incarnation}:{display_epoch}`. The scope is the
selected trusted **entire X11 server**. A window identifier is an action
precondition and capture association, not a security boundary. The two SHA-256
preimages are:

```text
scope:       trill.desktop.scope.v1\0 + session + \0 + incarnation + \0 + epoch
predecessor: trill.desktop.predecessor.v1\0 + session + \0 + incarnation + \0 + epoch + \0 + decimal(sequence)
```

Bootstrap is one private datagram with SCM_RIGHTS descriptors in order
`[effect SOCK_STREAM, observation SOCK_STREAM]`. The metadata offer and ACK bind
version 1, profile `trill.desktop.x11.v1`, identity and fixed display/window
metadata. The ACK transfers no descriptors and acknowledges composition only.
Each stream frame is a four-byte big-endian byte length followed by exact JSON.

Input requests are at most 8192 bytes and contain at most 32 typed key, pointer
movement or pointer button events. Each batch must release every key/button it
presses. They bind operation ID, exact destination, identity, expected input
sequence and expected window. The sequence is an adapter CAS, not application
revision. Reply size is at most 2048 bytes. `injected` binds prior and incremented
sequence and the fixed semantics `x11_server_injected`; `not_injected` is a closed
pre-effect refusal; `unknown` is never terminal. Partial input or uncertain I/O
cannot be described as a no-effect refusal.

The separate observation stream permits exact receipt lookup and capture only.
Capture is at most 1024 by 768 RGB pixels, at most 8 MiB encoded; the client checks
all lengths, identity/request correlation and the pixel SHA-256. The adapter's
bounded per-instance receipt cache is not a durable ledger. A new instance or
lost cache returns Unknown; neither a similar screenshot nor a new grant makes
old history known. The original owner preserves Indeterminate without replay.

The trusted launcher supplies Session an already connected X11 socket and exact
server PID, optionally a private 16-byte MIT cookie descriptor. The product does
not discover `DISPLAY`, select an endpoint from a model payload or treat an X11
window as isolation. Product launch flags are documented by the Desktop Session
module; Hepta receives the resulting private descriptor offer.

## Development and validation

The coherent review stages are strict wire/target parsing, original-owner typed
settlement plus private transports, and actual application qualification. These
changes must land together when the exported target is made available; the
original ledger must not temporarily expose generic desktop settlement.

Use the repository `just test` entry point before `just fix` and `just fmt`:

```sh
just test --locked -p codex-hepta-memory --lib \
  -E 'test(production_desktop) or test(notes_owner) or test(production_notes)'
just test --locked -p codex-hepta-agentd --lib \
  -E 'test(desktop_) or test(notes_tests) or test(production_composition)'
HEPTA_DESKTOP_SESSION_BIN=/absolute/pinned/trill-session \
HEPTA_DESKTOP_QUALIFICATION_OUTPUT=/absolute/result.json \
just test --locked -p codex-hepta-agentd --lib --run-ignored ignored-only \
  -E 'test(desktop_actual_x11)' --test-threads 1 --retries 0
```

The explicit ignored qualification starts its own Xvfb and stock `xmessage`,
uses the actual Session adapter and original owner SQLite/FinalUse path, refuses
an invalid signature before channel entry, withholds an actual native response,
then recovers the exact injection receipt through the independent lane without
another grant or dispatch. The stock application's exit is checked independently
and is reported separately from source terminal semantics. The issuer and initial
current cut are explicit fixtures: this test does not qualify production Root
custody or native Asterinas. Its `-ac` server is isolated test transport only;
production launcher authentication remains mandatory.
