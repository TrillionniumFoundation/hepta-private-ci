/* Retained-array arithmetic review, executed in a plain V8 isolate.
 * Inputs are the original native-report JSON, original trace UTF-8 bytes as text,
 * all 13 frozen source files as a path->text object, and a SHA256(text) function.
 * ZIP SHA256, central/local headers, member CRC32 and SHA256 were checked
 * separately before extracting these inputs; see INDEPENDENT_ARRAY_REVIEW.json.
 * This function does not execute model/project code or attest external custody.
 */
function reviewRetainedProjectedArrays(native, traceText, sources, sha256) {
  const sourceHead = "5a1db6f9da54d877e1660c4c964df0e227745719";
  const names = ["log_boundary", "mu", "sigma", "absolute_reset", "discount"];
  const readouts = ["expected_events", "discounted_events", "discounted_active_time", "call", "margin"];
  const canonical = value => Array.isArray(value)
    ? "[" + value.map(canonical).join(",") + "]"
    : value && typeof value === "object"
      ? "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}"
      : JSON.stringify(value);
  const close = (a, b) => a === b || (
    typeof a === "number" && typeof b === "number" && Number.isFinite(a) && Number.isFinite(b)
    && Math.abs(a-b) <= 1e-12 * Math.max(Math.abs(a), Math.abs(b), Number.MIN_VALUE));
  const errors = [], gateFailures = [];
  const phase = native.phases.find(p => p.label === "projected_gradients");
  const e = phase.tests.find(t => t.numerical_evidence?.schema === "hcsn-recorded-projected-gradient-audit-v1").numerical_evidence;
  const trace = traceText.trimEnd().split("\n").map(JSON.parse);
  const header = trace[0], footer = trace[trace.length-1], visits = trace.filter(r => r.kind === "visit");
  const footerStart = traceText.lastIndexOf("\n", traceText.length-2) + 1;
  if (!traceText.endsWith("\n")) errors.push("trace final newline");
  if (native.source_head !== sourceHead || native.returncode !== 0) errors.push("native source/returncode");
  if (canonical(native.source_before) !== canonical(native.source_after)) errors.push("source before/after");
  let sourceCount = 0;
  for (const [path, expected] of Object.entries(native.source_before)) {
    if (typeof sources[path] !== "string" || sha256(sources[path]) !== expected) errors.push("source hash: " + path);
    sourceCount++;
  }
  if (sourceCount !== 13) errors.push("source roster");
  for (const [label, expected] of [["projected_gradients", 9], ["existing_trace_regression", 14]]) {
    const p = native.phases.find(x => x.label === label);
    if (!p || p.tests_run !== expected || !p.success || p.failures || p.errors || p.skipped
      || p.tests.length !== expected || p.tests.some(t => t.outcome !== "pass")) errors.push("test phase: " + label);
  }
  if (e.visits.length !== 9 || visits.length !== 9 || e.audited_records !== 9
    || footer.retained_records !== 9 || footer.seen_records !== 9) errors.push("population");
  if (footer.truncated || footer.dropped_records || !e.complete_retained_coverage
    || !e.source_unchanged_during_audit || !e.source_matches_trace) errors.push("coverage/source flags");
  if (sha256(traceText) !== e.trace_sha256 || sha256(traceText) !== native.fixture_trace_sha256) errors.push("trace SHA");
  if (sha256(traceText.slice(0, footerStart)) !== footer.prefix_sha256) errors.push("trace prefix SHA");
  if (canonical(e.trace_summary) !== canonical(footer)
    || canonical(header.sources) !== canonical(footer.sources_after)) errors.push("trace source/footer");
  if (e.data_sha256 !== header.data_sha256 || e.configuration_sha256 !== header.configuration_sha256) errors.push("data/config identity");
  if (sha256(sources["qualification/hcsn_differentiable/training_domain_projected_gradients.py"]) !== e.auditor_sha256) errors.push("auditor hash");
  if (e.limits.absolute_tolerance !== 1e-7 || e.limits.relative_tolerance !== 5e-4
    || canonical(e.limits.relative_steps) !== "[0.00002,0.00001]") errors.push("limits");
  let coordinates = 0, maxAbsError = 0, maxGateRatio = 0, maxStepStabilityRatio = 0, maxRecordedEventReplayError = 0;
  let nullCoordinates = 0, zeroFDWithNonzeroAD = 0, maxDefinedRelativeError = 0, maxUndefinedAD = 0;
  let worstDefinedRelative = null, worstUndefinedRelative = null;
  const groups = {}, signals = Object.fromEntries(names.map(name => [name, {
    maxAbsAD: 0, maxAbsFD: 0, maxAbsError: 0, maxGateRatio: 0, maxStepRatio: 0, nonzeroAD: 0, zeroFDNonzeroAD: 0
  }]));
  for (let v = 0; v < e.visits.length; v++) {
    const a = e.visits[v], t = visits[v], layout = a.output_layout;
    if (a.index !== v || t.index !== v || ["episode_id", "update_index", "model_sha256"].some(k => a[k] !== t[k])) errors.push("visit identity " + v);
    if (canonical(layout.readouts) !== canonical(readouts) || layout.batch !== 1 || layout.probability_states !== 10) errors.push("layout " + v);
    if (a.ad.length !== 15 || a.fd_fine.length !== 15 || a.fd_coarse.length !== 15 || a.derivative_coordinates !== 75) errors.push("shape " + v);
    if (a.status !== "passed_projected_gradient_fixture" || !a.recorded_event_replay_verified || a.maximum_event_replay_error > 5e-11) errors.push("replay/status " + v);
    maxRecordedEventReplayError = Math.max(maxRecordedEventReplayError, a.maximum_event_replay_error);
    groups[a.update_index] ??= {visits: 0, modelHashes: []};
    groups[a.update_index].visits++;
    if (!groups[a.update_index].modelHashes.includes(a.model_sha256)) groups[a.update_index].modelHashes.push(a.model_sha256);
    for (let p = 0; p < 5; p++) {
      const param = a.parameters[p], name = names[p], signal = signals[name];
      if (param.parameter !== name) errors.push("parameter order " + v);
      const step = 2e-5 * Math.max(1, Math.abs(t.parameters[name]));
      if (!close(param.finite_difference_steps[0], step) || !close(param.finite_difference_steps[1], step/2)) errors.push("FD step " + v + "/" + name);
      let absolute = 0, ratio = 0, stability = 0, maxAD = 0, maxFD = 0, worst = 0;
      const relative = [];
      for (let output = 0; output < 15; output++) {
        if ([a.ad[output], a.fd_fine[output], a.fd_coarse[output]].some(row => !Array.isArray(row) || row.length !== 5)) throw Error("invalid matrix shape");
        const ad = a.ad[output][p], fd = a.fd_fine[output][p], coarse = a.fd_coarse[output][p];
        if ([ad, fd, coarse].some(x => typeof x !== "number" || !Number.isFinite(x))) throw Error("invalid numeric coordinate");
        coordinates++;
        const error = Math.abs(ad-fd);
        const r = error / (1e-7 + 5e-4 * Math.max(Math.abs(ad), Math.abs(fd)));
        const s = Math.abs(coarse-fd) / (1e-7 + 5e-4 * Math.max(Math.abs(coarse), Math.abs(fd)));
        if (r > 1 || s > 1) gateFailures.push({visit: v, parameter: name, output, ratio: r, stability: s});
        absolute = Math.max(absolute, error);
        if (r > ratio) { ratio = r; worst = output; }
        stability = Math.max(stability, s);
        maxAD = Math.max(maxAD, Math.abs(ad)); maxFD = Math.max(maxFD, Math.abs(fd));
        const rel = fd === 0 ? null : error / Math.abs(fd);
        relative.push(rel);
        if (rel === null) {
          nullCoordinates++;
          if (ad !== 0) { zeroFDWithNonzeroAD++; signal.zeroFDNonzeroAD++; }
          if (Math.abs(ad) > maxUndefinedAD) { maxUndefinedAD = Math.abs(ad); worstUndefinedRelative = {visit: v, output, parameter: name, ad, fd}; }
        } else if (rel > maxDefinedRelativeError) {
          maxDefinedRelativeError = rel; worstDefinedRelative = {visit: v, output, parameter: name, ad, fd, absoluteError: error};
        }
        if (ad !== 0) signal.nonzeroAD++;
      }
      const metrics = {maximum_absolute_error: absolute, maximum_absolute_ad: maxAD, maximum_absolute_fd: maxFD,
        maximum_tolerance_ratio: ratio, maximum_step_stability_ratio: stability};
      for (const [key, value] of Object.entries(metrics)) if (!close(param[key], value)) errors.push("summary " + v + "/" + name + "/" + key);
      if (param.ordinary_relative_errors.length !== 15 || relative.some((x, i) => x === null ? param.ordinary_relative_errors[i] !== null : !close(x, param.ordinary_relative_errors[i]))) errors.push("relative array " + v + "/" + name);
      const quantity = worst < 10 ? "probability[" + worst + "]" : readouts[worst-10];
      if (param.worst_coordinate.quantity !== quantity || param.worst_coordinate.batch_offset !== 0
        || !close(param.worst_coordinate.ad, a.ad[worst][p]) || !close(param.worst_coordinate.fd, a.fd_fine[worst][p])) errors.push("worst coordinate " + v + "/" + name);
      maxAbsError = Math.max(maxAbsError, absolute); maxGateRatio = Math.max(maxGateRatio, ratio); maxStepStabilityRatio = Math.max(maxStepStabilityRatio, stability);
      signal.maxAbsAD = Math.max(signal.maxAbsAD, maxAD); signal.maxAbsFD = Math.max(signal.maxAbsFD, maxFD);
      signal.maxAbsError = Math.max(signal.maxAbsError, absolute); signal.maxGateRatio = Math.max(signal.maxGateRatio, ratio); signal.maxStepRatio = Math.max(signal.maxStepRatio, stability);
    }
  }
  if (coordinates !== 675 || Object.values(signals).some(x => x.maxAbsAD === 0)) errors.push("coordinate count or signal");
  if (e.scientific_admission !== "HOLD_NO_GO" || e.full_numerical_admission !== "HOLD_NO_GO" || e.formal_training_replays !== 0) errors.push("scope promotion");
  return {errors, gateFailures, sourceFilesVerified: sourceCount, coordinates, visits: e.visits.length,
    groups, maxAbsError, maxGateRatio, maxStepStabilityRatio, maxRecordedEventReplayError, signals,
    ordinaryRelative: {nullCoordinates, zeroFDWithNonzeroAD, maxDefinedRelativeError, maxUndefinedAD,
      worstDefinedRelative, worstUndefinedRelative},
    traceSha256: sha256(traceText), tracePrefixSha256: sha256(traceText.slice(0, footerStart)),
    scientificAdmission: e.scientific_admission, formalTrainingReplays: e.formal_training_replays};
}
if (typeof module !== "undefined") module.exports = reviewRetainedProjectedArrays;
