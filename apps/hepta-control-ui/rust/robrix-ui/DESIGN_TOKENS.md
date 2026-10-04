# Shared Robrix visual themes

The three image-generated references requested on 2026-10-03 are design targets,
not screenshots or acceptance evidence. The implementation uses real Rust
Robrix-derived widgets; none of the images is installed as a full-window bitmap.

`VisualTheme` selects one local presentation preference. It does not select an
owner, session, identity, model, transport or authority profile. The default is
Aurora Graphite. The theme switch currently lasts for the application session;
cross-reload preference persistence is not implemented.

| Token | Obsidian Ice | Lunar Titanium | Aurora Graphite |
|---|---|---|---|
| Canvas | `#0c131d` | `#f3f5f7` | `#10111d` |
| Panel | `#151f2b` | `#e9eef1` | `#1a1a2e` |
| Raised surface | `#202e40` | `#ffffff` | `#222238` |
| Text | `#e8f2ff` | `#18232c` | `#eeebff` |
| Secondary text | `#a7b8ce` | `#52616d` | `#b4b0c9` |
| Accent | `#63bdff` | `#267d8c` | `#9585ff` |
| Edge | `#31506b` | `#c5d1d8` | `#37354f` |
| Selection | `#284665` | `#d4e7eb` | `#34305e` |
| Secondary accent | `#8ed9ff` | `#267d8c` | `#ffb3bc` |
| Conversation column | 300 px | 280 px | 248 px |
| Message treatment | Dark blue cards | Pale titanium cards | Open graphite timeline |

Lunar Titanium also uses the separately generated, UI-free landscape in
`resources/lunar-titanium.png`, bound by `resources/ASSETS.json`. A Rust Image
layer renders it behind the conversation with the pinned `ImageFit.CropToFill` mode and a small
rightward focal offset. It is hidden in the other themes. Message surfaces
protect foreground contrast. The original complete design mockups are never
used as application backgrounds.

The common desktop structure uses a 64 px navigation rail, the conversation
column, and the existing Dock. Below the existing 760 px breakpoint, the same
workspace uses the Robrix adaptive navigation path. The main tabs remain Chat
and Console. The theme selector is available in both layouts.

Typography uses 12 pt body and author text (approximately 16 CSS px), with
explicit IBM Plex, LXGW CJK and emoji fallback chains. Identity marks are code
drawn initials in 36 px framed avatars. Search is 40 px high; the composer has a
52 px editor, a compact truthful status line and outside margins. Fine SDF outlines and a
bounded shader gradient supply material depth without rendering fake telemetry.

Theme changes recolour existing widget instances and adjust the existing Dock
splitter. They do not reconstruct the conversation model or set editor text,
selection, undo, focus, owner fences, message order or scroll position. Switching
is rejected during active input composition. These are implementation contracts;
real browser and native interaction tests must still verify them.

The generated references include invented people, availability indicators,
attachments and model controls. They are not installed as production capabilities.
Only actual local drafts or the explicitly labelled deterministic owner fixture
drive the current host. Live owner composition and operational Console controls
remain separate incomplete work.

## Required visual and behavioral evidence

- Actual wide and narrow rendered screenshots for all three themes
- Readable English and CJK glyphs, with no clipped search or composer text
- Owner message order preserved from first to last, latest activity at the bottom
- Theme and Console round trips preserve conversation, draft, scroll and focus
- Long-history scrollback, jump-to-latest, keyboard and IME behavior
- Clear unavailable state when WebGL2 cannot be created
- Continuous-frame and resize observations in WebKit; diagnostic buffer variants
  do not qualify the unchanged production path

Compilation, generated design images and the older blue/gray screenshots do not
establish these outcomes. Source and CI reports must identify the exact theme,
host, fixture status and commit under observation.
