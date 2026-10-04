# Shared Robrix visual themes

The user's three image-generated references are design targets,
not screenshots or acceptance evidence. The implementation uses real Rust
Robrix-derived widgets; none of the images is installed as a full-window bitmap.

`VisualTheme` selects one local presentation preference. It does not select an
owner, session, identity, model, transport or authority profile. The default is
Aurora Graphite. The theme switch currently lasts for the application session;
cross-reload preference persistence is not implemented.

| Token | Obsidian Ice | Lunar Titanium | Aurora Graphite |
|---|---|---|---|
| Canvas | `#0c131d` | `#f7f6f2` | `#15191f` |
| Panel | `#151f2b` | `#dddcd9` | `#151a21` |
| Raised surface | `#202e40` | `#f9f8f6` | `#181d26` |
| Text | `#e8f2ff` | `#18232c` | `#eef1f4` |
| Secondary text | `#a7b8ce` | `#595953` | `#aab0bb` |
| Accent | `#63bdff` | `#18707d` | `#a5f0cc` |
| Edge | `#31506b` | `#dad8d4` | `#383e49` |
| Selection | `#284665` | `#c3d5d5` | `#282f38` |
| Secondary accent | `#8ed9ff` | `#ecc9ab` | `#9f95d5` |
| Conversation column | 300 px | 280 px | 248 px |
| Message treatment | Dark blue cards | Pale ceramic cards | Open assistant rows; user cards |

The existing theme names and order remain stable for local interaction and
capture identity. Aurora Graphite now targets the original B's neutral graphite
body with small mint/violet edge reflections. Lunar Titanium targets the original
C's warm ceramic body, platinum-gray sidebar, petrol accent and subtle warm
highlights. Both materials are drawn by the existing shared Rust widgets.
The prior diagonal sidebar decoration is retained only in Obsidian; the other
two themes use their local edge and surface shading.

The previously generated landscape `resources/lunar-titanium.png` is retained
with its original bytes and provenance in `resources/ASSETS.json`. It is still
packaged by the unchanged asset copier, but has no rendered Image layer in this
candidate. The original C reference has no landscape backdrop. Original design
mockups are never used as application backgrounds.

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

The B/C material revision is pending fresh shader compilation and rendered
browser/native evidence. Existing 9995 browser results describe its prior
palette and landscape, not this revision. The full original composition still
requires workspace/group navigation, channel controls, same-column author/time
rows, a real shared file-card presentation and the attachment tool area. This
material revision does not claim those missing regions or live capabilities.
