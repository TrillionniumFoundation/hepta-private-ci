# Hepta chat design

This is the normative UI design for the Robrix-derived application in
[`rust/robrix-ui`](rust/robrix-ui). It supersedes the unpublished egui/semantic-DOM
continuation at `6a94f019aeee`; those renderers are not the chosen UI basis.

## Actual Robrix source reuse

Hepta adapts Robrix `f2208f16184e1b2d8307dc9f98375e47b1fcd677`, using its
Makepad revision `337566c8b25d47f7e4fff6a202157b65bf183330`. The application
registers and uses the derived widgets, rather than treating upstream as a
visual reference or an unused source snapshot:

- `robrix/dock.rs`: Robrix tab, splitter, close-button and dock definitions
- `robrix/home.rs`: sidebar/main dock split and adaptive desktop/narrow layout
- `robrix/rooms.rs`: conversation-row hierarchy, selection and hover treatment
- `robrix/room.rs`: message hierarchy, `PortalList` timeline and composer placement
- `robrix/composer.rs`: capped composer, overlay and bottom-aligned input/send row
- `app.rs`: Makepad application lifecycle and widget registration

[`UPSTREAM.json`](rust/robrix-ui/UPSTREAM.json) records original files, source
regions, hashes and adaptations. Preserve the upstream copyright and
[MIT notice](rust/robrix-ui/licenses/ROBRIX-MIT.txt). Robrix logos and separately
licensed SVG assets are excluded. Hepta supplies its own readable sci-fi palette.

## Conversation-first interaction

Open Conversations first. On wide screens, show conversation navigation beside
the active timeline and bottom composer. On narrow screens, show one principal
pane with an explicit route back to conversations. Keep drafts, selection and
scroll position when navigating between conversations or tabs.

Console is a secondary tab inside this same chat application. It must not become
the landing page or a separate application shell. Its eventual operational
controls must retain their existing owner and authorization boundaries.

Use the adapted Robrix widgets for both native and Web. Layout, navigation,
message presentation and composition logic remain Rust and the embedded Makepad
UI definitions. Makepad's generated browser JavaScript handles framework startup,
rendering and input bridging; it is not a separately authored application UI.
Robrix itself does not advertise a shipped Web target, so Hepta's Web build and
runtime behavior need their own verification.

Record any framework compatibility adaptation with its exact source and package
hashes. The Web build's isolated clock patch and static message-bridge emission
preserve the shared Rust UI; they do not define a second application renderer.

## State and behavior

`presentation.rs` projects the existing `hepta-control-core` chat state into the
Robrix-derived widgets and forwards local UI actions. It does not create a
runtime, signer, grant issuer, transport owner or second transcript store.
Matrix service and authentication behavior are outside this adaptation.

Local drafts stay visibly unsent. Only authenticated owner observations can
supply messages, delivery states or completion. Console connectivity does not
grant chat authority. Without an installed owner/signer bridge, show the reason
Send is unavailable; never turn a local edit or button click into a sent receipt.
Keep principal-scoped drafts and stale-observation fencing in the existing core.

The composer must preserve Unicode and multiline input, respect IME composition,
and retain drafts across navigation. Enter during preedit must not send.
The timeline must preserve deliberate scrollback, follow the end only when
appropriate, and offer a clear route to newer messages. Maintain readable text,
visible keyboard focus and explicit status labels; glow, animation and color
must not carry essential meaning alone.

These are intended interactions, not claims that the in-progress host has been
validated. Current implementation and verification limits are recorded in the
[application guide](README.md); build details are in the [Rust guide](rust/README.md).

## Requested visual variants (2026-10-03)

The shared Rust host is being updated against three image-generated reference
directions: Obsidian Ice, Lunar Titanium and Aurora Graphite. The canonical
implementation token and acceptance contract is
[`DESIGN_TOKENS.md`](rust/robrix-ui/DESIGN_TOKENS.md). This covers controlled
sidebar widths, message cards versus open text, material and background layers,
and one real local theme selector. No reference image implies a real person,
online status, attachment capability or model integration. These variants remain
candidates until actual host screenshots and theme/Console/input/scroll round
trips pass; older screenshots do not qualify the revised design.
