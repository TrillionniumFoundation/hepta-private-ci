# Current Index contract and retained v8 template history

The Index sections below remain the active contract for `template_index`.
The streaming parser and render-policy sections are retained historical v8
documentation, not the current parse/render wire contract. Current v9
parse and render are specified by `template_parse_buffer_contract.json`
and `template_render_buffer_contract.json`; their transport layouts must
not be interchanged with the historical sections below.

The current Rust parse adapter passes native-selected, validated original
source ranges to the Index Builder. HIA selects unique names and their
order; `finish()` moves owned strings by native node ID into a vector.
Templates keep that vector, not a live index. The v9 renderer serializes
its exact iterator; the old Index query wrappers are retained for tests.
This composition does not claim indexed v9 variable lookup or transfer
the former renderer's performance qualification.

---

## Retained original document

# Template native component contract

The template implementation uses three HIA components: a streaming parser, a render
policy machine, and a shared AVL index. The Rust feature remains opt-in. The
native template path delegates delimiter recognition, Unicode trimming, key
comparison, duplicate detection, sorted traversal, lookup, usage tracking,
render validation precedence, and segment decisions to these components. Rust
owns allocations, strings, AST storage, generic iterator effects, formatting,
and checked conversion of native results into the unchanged public API.

## Borrowed buffers and the pinned compiler

The static x86-64 GNU export receives three pointer/length pairs. Each length is
a full 64-bit descriptor word. The caller supplies live allocations with valid
extents; the mutable buffers do not overlap each other or the source. No native
component retains a pointer after a call. The Rust transport supplies these
properties using separate slices and vectors.

At Hepta revision `f33d8da316de8fdf27b504371f1a5310997ff548`, the native wrapper
copies all six 64-bit arguments into descriptors. Its byte-load/store emission
compares the full 64-bit index with the descriptor length before accessing the
byte (`cmp rcx, rdx; jb; ud2`). The compiler and Python seed wrappers' 1 MiB
workspace limits are separate from this emitted static data interface. These components change neither the compiler nor those seed limits. It also does not
infer pointer validity from an unchecked foreign caller's claimed length.

The source, emitted-wrapper inspection and actual large-buffer evidence
identified in [`verification.json`](verification.json) support this distinction. The index ABI test uses a 4,194,496-byte
node allocation, a 4,194,313-byte key buffer, a 2,097,153-byte query, and a sparse
4,294,971,392-byte mapping with real key offsets above `u32::MAX`. The latter is
an address/length test and touches only a small part of the demand-zero mapping.

## Parser events and errors

The parser borrows a window of at most 4,096 bytes and writes a 24-byte result:
three little-endian u64 words `(event, begin, end)`. Its 48-byte workspace holds
total source length, current byte position, opening-delimiter anchor and
trimmed placeholder begin/end at offsets 0/8/16/24/32. Byte 40 records phase
(outside, inside, finished); byte 41 says whether the presented window reaches
EOF. The initial workspace is zero except for total source length.

Successful calls commit one literal span, placeholder span, parser-progress
event or completion. Span offsets address the original source; Rust owns the
AST and copies only the strings required by the existing public representation.
Partial UTF-8 scalars or delimiters are borrowed again with subsequent bytes,
so the framing window does not cap total source or placeholder length.

The grammar preserves four-brace escapes before ordinary opening/closing
recognition, nested-delimiter errors, Rust Unicode whitespace trimming and
original UTF-8 byte-position error anchors. An opening event commits its anchor
separately. A subsequent syntax error leaves the current output and workspace
unchanged while retaining that earlier successful opening event. Empty,
nested, unmatched-closing and unterminated-placeholder errors remain distinct.
Invalid UTF-8, state or buffers are separate ABI failures.

## Index storage

The workspace begins with a 128-byte header. Full little-endian u64 words hold
count/root/head/seen-key-extent at 0/8/16/24, command and three arguments at
32/40/48/56, query cursor/offset/length/visited at 64/72/80/88, phase and mark at
96/104, and zero reserved words at 112/120. Phase 0 is ready; phase 1 accepts
only the pending query's continuation command.

Each node occupies a 64-byte slot. Its fields are left/right/parent/height/next/
used/key-begin/key-length at offsets 0/8/16/24/32/40/48/56. Links are one-based
with zero for null. Public stable IDs are link minus one. New slots are zeroed,
IDs are never reused, and callers keep all earlier key bytes immutable while
allowing the source arena to grow. Nodes are opaque native state.

The kernel encodes fields with 1, 4 or 8 individual byte loads/stores according to the
current field bound. Links use node count; ranges use key extent; height and
used fit in one byte. The physical slot size stays eight bytes. Zero-filled
new slots and monotonically growing bounds preserve the high zero bytes when
a field widens. Header and result words always use all eight bytes. The Rust
transport does not interpret or mutate node fields.

Before node access, count is bounded by `(workspace_length - 128) / 64`, and
links used as addresses are checked against count. Therefore the last byte of
any node field fits its actual allocation without overflowing its offset.
Key ranges use `begin <= key_length` and `size <= key_length - begin` before
forming end positions. Query windows use bounded remaining lengths. The AVL
path limit of 96 exceeds the height of a valid AVL tree that could fit the
64-bit node allocation; it also bounds traversal of inconsistent state.

## Index commands and results

All calls require an output of at least 32 bytes. Scalar results are four u64
words `(event, a, b, c)` and return 32. Invalid input/state returns `0xffffffff`;
short output returns `0xfffffffe`. These errors leave both mutable buffers
unchanged from their state at function entry. The caller's command framing
before the call is separate from this guarantee.

| Command         | Input arguments                                                       | Result                                                                  |
| --------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 0 Insert        | begin, end, 0                                                         | event 0 New(id) or 1 Existing(id)                                       |
| 1 Ordered       | `u64::MAX` for first page, otherwise next link; already seen count; 0 | event 2: next link, page count, cumulative count; IDs follow at byte 32 |
| 2 Find          | query length, 0, first chunk length                                   | event 3 Found(id), 4 Missing, or 5 NeedQuery(offset)                    |
| 3 FindAndMark   | same as Find                                                          | same, with used set only for a fully validated match                    |
| 4 ContinueQuery | same query length, requested offset, chunk length                     | resumes the pending lookup                                              |
| 5 FirstUnused   | 0, 0, 0                                                               | event 6 Unused(id) or 4 Missing                                         |

Unused result operands are zero. Ordered pages contain at most 1,024 IDs and
return `32 + 8 * page_count` bytes; next link zero ends traversal. Query chunks
have at most 4,096 bytes in output starting at byte 32. A search may request an
earlier window after moving to another node. This is a byte protocol: splitting
a valid UTF-8 scalar across windows does not change comparison semantics.

Insertion validates the relevant AVL path and rotation metadata before writes.
Ordered traversal checks its page before publishing it. Find validates the
selected path, key ranges and continuation progress; it does not re-audit every
unvisited node. This is an opaque state interface created by the trusted native
kernel, not a format for loading arbitrary external tree files.

## Render policy and public semantics

The render machine uses a 40-byte command and 64-byte state with bounded u64
counts. The native index supplies insertion and lookup outcomes; the policy
chooses acceptance, the next placeholder, the unused-key check, the next
segment, the selected literal/value, or completion. Semantic Duplicate/Missing/
Extra/MissingSegment returns are atomic and distinct from malformed ABI input.

The original generic effects are preserved: `K::as_ref` precedes `V::as_ref`,
the duplicate item's value conversion still occurs, and no next iterator item
is requested after that duplicate. All input values are consumed before missing
or extra validation. Missing placeholders are reported in sorted order before
any extra value; extras use the smallest unused key. Values are appended
verbatim. Native placeholders retain canonical native-selected order and the
original Debug, Clone, Eq and exact-size public iterator behavior.

## Qualification limits

[`verification.json`](verification.json) is the canonical record of exact
sources, native build identity, original-Rust comparisons, owner/consumer
gates, large-buffer inspection and error/no-write evidence. The native target
is Linux x86-64 GNU and the feature remains opt-in.

The installed full CLI contains the three template symbols and passes the
listed relocation/startup/patch checks. Installation is a component integration
checkpoint; it does not by itself execute every template operation or prove
complete product ownership. Rust still supplies allocations, owned AST/string
storage, generic iterator effects, formatting and checked native framing.

Functional comparisons passed, but render performance equivalence remains
open: the recorded 50,000-key runs take about 0.56–0.58 seconds natively versus
0.014–0.021 seconds in the original Rust. Default native dispatch, the full
cross-platform release and Rust retirement remain unqualified. No generated
libraries, bootstrap stages or development versions belong in this source
contract.
