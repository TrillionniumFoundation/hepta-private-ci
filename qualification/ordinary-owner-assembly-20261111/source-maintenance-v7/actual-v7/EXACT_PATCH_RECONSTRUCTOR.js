
"use strict";
function requireIt(ok, message) { if (!ok) throw new Error(message); }
function linesWithEndings(text) {
 const result = []; let start = 0;
 for (let n = 0; n < text.length; n++) if (text.charCodeAt(n) === 10) {
  result.push(text.slice(start, n + 1)); start = n + 1;
 }
 if (start < text.length) result.push(text.slice(start));
 return result;
}
function patchLineText(line) { return line.endsWith("\n") ? line.slice(0, -1) : line; }
function parseFullIndexPatch(text) {
 const lines = linesWithEndings(text), files = []; let at = 0;
 while (at < lines.length) {
  const diff = /^diff --git a\/([A-Za-z0-9_./-]+) b\/([A-Za-z0-9_./-]+)$/.exec(patchLineText(lines[at]));
  requireIt(diff, "Expected exact unquoted git diff header at patch line " + (at + 1));
  requireIt(diff[1] === diff[2], "Renames are not accepted: " + diff[1]);
  const file = {path: diff[1], patch_header_line: at + 1, hunks: []}; at++;
  const index = /^index ([0-9a-f]{40})\.\.([0-9a-f]{40})(?: (100644|100755))?$/.exec(patchLineText(lines[at] || ""));
  requireIt(index, "Expected full 40-character index hashes for " + file.path);
  file.pre_blob = index[1]; file.post_blob = index[2]; file.mode = index[3] || null; at++;
  requireIt(patchLineText(lines[at] || "") === "--- a/" + file.path, "Old path mismatch " + file.path); at++;
  requireIt(patchLineText(lines[at] || "") === "+++ b/" + file.path, "New path mismatch " + file.path); at++;
  while (at < lines.length && !patchLineText(lines[at]).startsWith("diff --git ")) {
   const match = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/.exec(patchLineText(lines[at]));
   requireIt(match, "Expected hunk header for " + file.path + " at patch line " + (at + 1));
   const h = {
    old_start: Number(match[1]), old_count: match[2] === undefined ? 1 : Number(match[2]),
    new_start: Number(match[3]), new_count: match[4] === undefined ? 1 : Number(match[4]),
    heading: match[5], patch_header_line: at + 1, operations: []
   };
   for (const key of ["old_start", "old_count", "new_start", "new_count"])
    requireIt(Number.isSafeInteger(h[key]) && h[key] >= 0, "Invalid hunk coordinate");
   requireIt(h.old_count === 0 || h.old_start > 0, "Nonempty old hunk has zero start");
   requireIt(h.new_count === 0 || h.new_start > 0, "Nonempty new hunk has zero start");
   at++; let oldSeen = 0, newSeen = 0;
   while (at < lines.length) {
    const raw = lines[at], body = patchLineText(raw);
    if (body === "\\ No newline at end of file") {
     const previous = h.operations[h.operations.length - 1];
     requireIt(previous && !previous.no_final_newline, "Orphan or duplicate EOF marker");
     requireIt(previous.line.endsWith("\n"), "EOF marker without patch-line delimiter");
     previous.line = previous.line.slice(0, -1);
     previous.no_final_newline = true; at++; continue;
    }
    if (oldSeen === h.old_count && newSeen === h.new_count) break;
    const operation = raw[0];
    requireIt(operation === " " || operation === "-" || operation === "+",
     "Invalid content prefix for " + file.path + " patch line " + (at + 1));
    if (operation !== "+") oldSeen++;
    if (operation !== "-") newSeen++;
    requireIt(oldSeen <= h.old_count && newSeen <= h.new_count,
     "Hunk line count overrun for " + file.path);
    h.operations.push({kind: operation, line: raw.slice(1), patch_line: at + 1, no_final_newline: false});
    at++;
   }
   requireIt(oldSeen === h.old_count && newSeen === h.new_count,
    "Incomplete hunk for " + file.path);
   file.hunks.push(h);
  }
  requireIt(file.hunks.length > 0, "No text hunks for " + file.path);
  files.push(file);
 }
 requireIt(new Set(files.map(f => f.path)).size === files.length, "Repeated file section");
 return files;
}
function replayFile(source, file, reverse) {
 const original = linesWithEndings(source), result = []; let cursor = 0;
 for (let index = 0; index < file.hunks.length; index++) {
  const h = file.hunks[index], oldStart = reverse ? h.new_start : h.old_start;
  const oldCount = reverse ? h.new_count : h.old_count;
  const newStart = reverse ? h.old_start : h.new_start;
  const newCount = reverse ? h.old_count : h.new_count;
  const oldOffset = oldCount === 0 ? oldStart : oldStart - 1;
  const newOffset = newCount === 0 ? newStart : newStart - 1;
  requireIt(oldOffset >= cursor && oldOffset <= original.length,
   "Invalid source hunk position " + file.path + " #" + index);
  result.push(...original.slice(cursor, oldOffset)); cursor = oldOffset;
  requireIt(result.length === newOffset,
   "New-position mismatch " + file.path + " #" + index);
  let consumed = 0, produced = 0;
  for (const op of h.operations) {
   const kind = reverse ? op.kind === "+" ? "-" : op.kind === "-" ? "+" : " " : op.kind;
   if (kind !== "+") {
    requireIt(cursor < original.length && original[cursor] === op.line,
     "Exact positioned source-line mismatch " + file.path + " hunk #" + index + " patch line " + op.patch_line);
    cursor++; consumed++;
   }
   if (kind !== "-") { result.push(op.line); produced++; }
  }
  requireIt(consumed === oldCount && produced === newCount,
   "Applied hunk count mismatch " + file.path + " #" + index);
  requireIt(result.length === newOffset + newCount, "Applied hunk destination mismatch");
 }
 result.push(...original.slice(cursor));
 for (let i = 0; i + 1 < result.length; i++)
  requireIt(result[i].endsWith("\n"), "An unterminated source line was placed before EOF");
 return result.join("");
}
function reconstruct(patch, sources, expected) {
 const files = parseFullIndexPatch(patch), declared = new Map(expected.map(x => [x.path, x]));
 requireIt(files.length === declared.size, "Patch/inventory file-count mismatch");
 const results = [];
 for (const file of files) {
  const spec = declared.get(file.path);
  requireIt(spec, "Unexpected path in patch " + file.path);
  requireIt(file.pre_blob === spec.pre_blob && file.post_blob === spec.post_blob,
   "Full-index header differs from actual manifest for " + file.path);
  const source = sources[file.path];
  requireIt(typeof source === "string", "Missing exact preimage for " + file.path);
  const post = replayFile(source, file, false);
  requireIt(replayFile(post, file, true) === source, "Reverse byte reconstruction mismatch");
  results.push({path: file.path, pre_blob: file.pre_blob, post_blob: file.post_blob, post,
   hunk_count: file.hunks.length, no_newline_markers: file.hunks.reduce((n,h) => n + h.operations.filter(o => o.no_final_newline).length, 0),
   hunk_positions: file.hunks.map(h => ({old_start: h.old_start, old_count: h.old_count, new_start: h.new_start, new_count: h.new_count, patch_header_line: h.patch_header_line}))});
 }
 return results;
}
return {linesWithEndings, parseFullIndexPatch, replayFile, reconstruct};
