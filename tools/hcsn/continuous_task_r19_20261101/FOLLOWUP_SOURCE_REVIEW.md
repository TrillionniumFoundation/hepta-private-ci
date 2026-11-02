# Source-only review of prospective local-step followup

The reviewer read `followup.py` and `FOLLOWUP_PROTOCOL.json` before any followup
evaluation. No numerical solver was run for this review. The original seven
frozen files and original failed confirmation were not modified.

The followup retains all thirteen coefficient coordinates, the same three
profiles, the same two meshes, and the original `1e-6` scaled whole-array bound.
Both newly declared step sizes (`1e-7`, `3e-8`) are applied in every case. The
finite difference uses plus and minus values from the unchanged R18 solver,
with its own perturbation helper previously reviewed in the frozen audit. The
candidate supplies only the analytic tangent and branch masks. All grid cells
enter the scaled error maximum; changed branch cells are not excluded.

The witness location is the argmax of the same whole-array error used by the
gate. Its stored plus, minus and tangent operands permit independent arithmetic
verification of that worst-cell error. Whole-array hashes use contiguous
little-endian IEEE binary64 bytes in C order, without an array header; the
corresponding shape is stored. Hashes establish reproducible identity if arrays
are independently regenerated. They do not make the arrays available for a
record-only reconstruction of all finite differences, which is explicitly
disclosed in the followup results schema.

The reviewer found no formula or indexing defect in this separate followup.
The final source asserts the imported candidate's parameter ordering and reads
the original confirmation, requiring its original `passed` field to be false.
The declared followup freeze includes that original result and every original
frozen source file along with the followup source, protocol and this review.
Its hash checks execute before evaluation; input Git blob checks remain intact.
The original failed gate must remain failed whatever this new campaign returns.

Smaller perturbations can test derivatives within the selected local branch.
They cannot qualify derivatives through action switches, time-delay admission
changes, a moving domain, continuum free-boundary limits, or the full financial
or neural model. No global gradient/adoption conclusion follows from passing.
