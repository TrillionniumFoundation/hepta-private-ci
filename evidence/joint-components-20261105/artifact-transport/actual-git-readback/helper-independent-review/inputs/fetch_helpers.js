const READBACK_ROOT = "/workspace/scratch/93bfcfe29fc8/actual-archive-git-readback";
const RECEIVER = "/workspace/scratch/93bfcfe29fc8/w1/git-blob-receiver-v1/receive_git_blob.py";
function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }
function utf8Bytes(value) {
  let total = 0;
  for (const character of value) {
    const point = character.codePointAt(0);
    total += point <= 0x7f ? 1 : point <= 0x7ff ? 2 : point <= 0xffff ? 3 : 4;
  }
  return total;
}
async function awaitReady(session, key) {
  let current = session;
  let output = session.output || "";
  const deadline = Date.now() + 15000;
  while (current.session_id && !output.includes("READY")) {
    store(key, {state: "WAITING_FOR_READY_SAME_SESSION", session_id: current.session_id, output});
    if (Date.now() >= deadline) throw Error("Receiver READY remains unknown; reconcile same session: " + current.session_id);
    current = await tools.write_stdin({session_id: current.session_id, chars: "", yield_time_ms: 1000, max_output_tokens: 1500});
    output += current.output || "";
  }
  return {...current, output};
}
async function settleLocal(session, key) {
  let current = session;
  const output = [session.output || ""];
  const deadline = Date.now() + 60000;
  while (current.session_id) {
    store(key, {state: "INPUT_ATTEMPTED_WAITING_FOR_TERMINAL_SAME_SESSION", session_id: current.session_id, output: output.join("")});
    if (Date.now() >= deadline) throw Error("Receiver terminal remains unknown; reconcile same session: " + current.session_id);
    current = await tools.write_stdin({session_id: current.session_id, chars: "", yield_time_ms: 1000, max_output_tokens: 1500});
    output.push(current.output || "");
  }
  return {...current, output: output.join("")};
}
async function captureActualRpc(value, path) {
  const rpcKey = "actual-control-rpc:" + path;
  const stateKey = "actual-control-state:" + path;
  store(rpcKey, value);
  store(stateKey, {state: "RECEIVED_LAUNCH_NOT_YET_CONFIRMED", path});
  const raw = JSON.stringify(value);
  const size = utf8Bytes(raw);
  const command = ["python", "-B", READBACK_ROOT + "/capture_raw_rpc.py", path, size].map(shellQuote).join(" ");
  const initial = await tools.exec_command({cmd: command, tty: true, yield_time_ms: 1000, max_output_tokens: 1000});
  store(stateKey, {state: "CAPTURE_CREATED", ...initial});
  const started = await awaitReady(initial, stateKey);
  if (!started.session_id || !started.output.includes("READY")) {
    throw Error("Actual RPC retained in session store after receiver pre-READY failure: " + JSON.stringify(started));
  }
  store(stateKey, {state: "INPUT_WRITE_ABOUT_TO_BE_ATTEMPTED", session_id: started.session_id, bytes: size});
  const sent = await tools.write_stdin({session_id: started.session_id, chars: raw, yield_time_ms: 1000, max_output_tokens: 1500});
  const terminal = sent.session_id ? await settleLocal(sent, stateKey) : sent;
  if (terminal.exit_code !== 0 || !((sent.output || "") + (terminal.output || "")).includes("SAVED_ACTUAL_RPC")) {
    throw Error("Raw RPC capture did not complete: " + JSON.stringify(terminal));
  }
  store(stateKey, {state: "CONFIRMED_SAVED_ACTUAL_RPC", path, bytes: size, exit_code: terminal.exit_code});
  store(rpcKey, null);
  return {path, bytes: size, terminal};
}
async function fetchAssignedBlob(row) {
  const result = await tools.mcp__codex_apps__github_fetch_blob(row.request);
  const rpcKey = "actual-blob-rpc:" + row.receipt_directory;
  const stateKey = "actual-blob-state:" + row.receipt_directory;
  store(rpcKey, result);
  store(stateKey, {state: "RECEIVED_LAUNCH_NOT_YET_CONFIRMED", request: row.request, receipt_directory: row.receipt_directory});
  const raw = JSON.stringify(result);
  const size = utf8Bytes(raw);
  const args = ["python", "-B", RECEIVER, "--metadata", row.metadata_path,
    "--expected-metadata-sha256", row.metadata_sha256, "--rpc-bytes", size,
    "--output", row.receipt_directory, "--data-root", READBACK_ROOT + "/data",
    "--payload-path", row.payload_path];
  const initial = await tools.exec_command({cmd: args.map(shellQuote).join(" "), tty: true, yield_time_ms: 1000, max_output_tokens: 1000});
  store(stateKey, {state: "RECEIVER_CREATED", ...initial});
  const started = await awaitReady(initial, stateKey);
  if (!started.session_id || !started.output.includes("READY")) {
    const fallback = row.receipt_directory + ".pre-ready-failure.raw.json";
    await captureActualRpc(result, fallback);
    throw Error("Blob receiver pre-READY failure; full actual RPC saved: " + fallback + " " + JSON.stringify(started));
  }
  store(stateKey, {state: "INPUT_WRITE_ABOUT_TO_BE_ATTEMPTED", session_id: started.session_id, bytes: size});
  const sent = await tools.write_stdin({session_id: started.session_id, chars: raw, yield_time_ms: 1000, max_output_tokens: 1500});
  const terminal = sent.session_id ? await settleLocal(sent, stateKey) : sent;
  const output = (sent.output || "") + (terminal.output || "");
  if (terminal.exit_code !== 0 || !output.includes("PASS_ACTUAL_BYTES")) {
    throw Error("Actual RPC preserved, blob receiver not complete: " + row.transport_path + " " + JSON.stringify(terminal));
  }
  store(stateKey, {state: "CONFIRMED_VERIFIED_ACTUAL_BYTES", receipt_directory: row.receipt_directory, exit_code: terminal.exit_code});
  store(rpcKey, null);
  return {path: row.transport_path, receipt_directory: row.receipt_directory, exit_code: terminal.exit_code};
}
