export function cleanLogLine(line) {
  return line.replace(/\uFEFF/g, "")
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ?/, "");
}
export function parseBazelTargetTables(raw) {
  const lines = raw.split(/\r?\n/);
  const tables = [];
  let pending = [];
  for (let i = 0; i < lines.length; i++) {
    const body = cleanLogLine(lines[i]);
    const row = body.match(/^(\/\/\S+)\s+(?:(\(cached\))\s+)?(PASSED|FAILED|FLAKY|SKIPPED|TIMEOUT|NO STATUS)\b(.*)$/);
    if (row) {
      pending.push({ label: row[1], status: row[3], cached: Boolean(row[2]), line: i + 1, detail: row[4].trim() });
      continue;
    }
    const summary = body.match(/^Executed (\d+) out of (\d+) tests?: (.*)$/);
    if (!summary) continue;
    const pass = summary[3].match(/(\d+) tests? pass(?:es)?\b/);
    const fail = summary[3].match(/(\d+) (?:tests? )?fail(?:s)? locally\b/);
    const skip = summary[3].match(/(\d+) (?:tests? )?(?:were |was )?skipped\b/);
    const headline = { executed_targets: Number(summary[1]), total_targets: Number(summary[2]), pass_including_flaky: Number(pass?.[1] ?? 0), failed_including_timeout: Number(fail?.[1] ?? 0), skipped: Number(skip?.[1] ?? 0) };
    const counts = { PASSED: 0, FLAKY: 0, FAILED: 0, TIMEOUT: 0, SKIPPED: 0, "NO STATUS": 0, cached_PASSED: 0, noncached_PASSED: 0, noncached_observed_targets: 0 };
    const labels = new Set();
    for (const r of pending) {
      if (labels.has(r.label)) throw new Error("Duplicate target in one summary table at " + r.line);
      labels.add(r.label);
      counts[r.status]++;
      if (r.cached && r.status !== "PASSED") throw new Error("Unreviewed cached status at " + r.line);
      if (r.status === "PASSED") counts[r.cached ? "cached_PASSED" : "noncached_PASSED"]++;
      if (!r.cached && r.status !== "SKIPPED" && r.status !== "NO STATUS") counts.noncached_observed_targets++;
    }
    if (pending.length !== headline.total_targets) throw new Error("Target table length mismatch at summary " + (i + 1));
    if (counts.PASSED + counts.FLAKY !== headline.pass_including_flaky) throw new Error("Headline passing-target mismatch");
    if (counts.FAILED + counts.TIMEOUT !== headline.failed_including_timeout) throw new Error("Headline failed-target mismatch");
    if (counts.SKIPPED !== headline.skipped) throw new Error("Headline skipped-target mismatch");
    if (counts.noncached_observed_targets !== headline.executed_targets) throw new Error("Executed-target mismatch");
    if (counts["NO STATUS"] !== 0) throw new Error("Unclassified target terminal status");
    tables.push({ summary_line: i + 1, original_summary: lines[i], headline, counts, rows: pending });
    pending = [];
  }
  if (pending.length) throw new Error("Target rows without a following Executed summary");
  if (!tables.length) throw new Error("No complete final target table observed");
  return { tables, line_count: lines.length, normalized_for_parsing_only: ["GitHub timestamp prefix", "ANSI CSI display escapes", "U+FEFF"], raw_text_not_modified: true };
}
export function inspectMacMemoryAssertion(raw) {
  const original = raw.split(/\r?\n/), lines = original.map(cleanLogLine);
  const name = "cognitive_runtime_tests::product_v2_reports_peer_truncation_before_aggregation";
  const stdoutMarker = "---- " + name + " stdout ----";
  const headings = [];
  for (let i = 0; i < lines.length; i++) if (lines[i] === stdoutMarker) headings.push(i);
  if (headings.length !== 2) throw new Error("Unreviewed assertion display count");
  const displays = headings.map(start => {
    const terminal = lines.findIndex((s, i) => i > start && s.startsWith("test result:"));
    if (terminal < 0) throw new Error("Missing suite terminal");
    const block = lines.slice(start, terminal + 1);
    const panic = block.find(s => s.includes("panicked at hepta-memory/src/cognitive_runtime_tests.rs:466:5:"));
    if (!panic || !block.includes("<0") || !block.includes(">16")) throw new Error("Original 0/16 assertion not found");
    if (!block.some(s => s === "test result: FAILED. 419 passed; 1 failed; 9 ignored; 0 measured; 0 filtered out; finished in 267.84s")) throw new Error("Unexpected memory suite terminal");
    return { start_line: start + 1, terminal_line: terminal + 1, panic_line: panic, observed_left: 0, expected_right: 16, suite_result: { passed: 419, failed: 1, ignored: 9, measured: 0, filtered_out: 0, elapsed_seconds: 267.84 }, original_selected_lines: original.slice(start, terminal + 1) };
  });
  if (displays[0].panic_line !== displays[1].panic_line) throw new Error("Display panic identities differ");
  const tailMarker = "##[group]Bazel test log tail for //codex-rs/hepta-memory:hepta-memory-unit-tests";
  const tail = lines.indexOf(tailMarker);
  if (tail < 0 || tail >= headings[1] || tail <= headings[0]) throw new Error("Second display not bound to explicit test-log tail group");
  const caseTerminalLines = lines.flatMap((s, i) => s === "test " + name + " ... FAILED" ? [i + 1] : []);
  if (caseTerminalLines.length !== 1) throw new Error("Unreviewed native case terminal multiplicity");
  return { name, file_line: "hepta-memory/src/cognitive_runtime_tests.rs:466:5", observed_left: 0, expected_right: 16, original_case_terminal_lines: caseTerminalLines, assertion_displays: displays, second_display_tail_group_line: tail + 1, observed_native_case_failures: 1, log_tail_is_not_another_execution: true, typed_failure_category_observed: false, root_cause: "UNRESOLVED" };
}
