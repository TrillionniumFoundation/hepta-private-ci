// Run in the tool orchestration environment after the publication job completes.
// The receipt describes a read-back commit; it is added in a follow-up commit.
(async () => {
  const repo = "TrillionniumFoundation/hepta-private-ci";
  const root = "/workspace/scratch/d831a963ef2f/hepta-analytic/";
  const run = "/tmp/aen-round3-20261028/";
  const prefix = "experiments/analytic_event_neuron/round3/";
  const q = s => "'" + s.replace(/'/g, "'\\''") + "'";
  const require = (ok, message) => { if (!ok) throw Error(message); };
  async function py(code, limit = 50000) {
    let value = await tools.exec_command({cmd: "python -c " + q(code), max_output_tokens: limit});
    let output = value.output;
    while (value.session_id && value.exit_code === undefined) {
      value = await tools.write_stdin({session_id: value.session_id, chars: "", yield_time_ms: 1000, max_output_tokens: limit});
      output += value.output;
    }
    require(value.exit_code === 0, JSON.stringify(value));
    return output.trim();
  }
  async function get(url) {
    const result = await tools.mcp__codex_apps__github_fetch({url});
    require(!result.isError, JSON.stringify(result));
    return JSON.parse(result.structuredContent.content);
  }
  const state = JSON.parse(await py("from pathlib import Path; print(Path('/tmp/aen-r3-publication-state.json').read_text())"));
  const ref = await get("https://api.github.com/repos/" + repo + "/git/ref/heads/research/analytic-event-neuron-20261027");
  require(ref.object.sha === state.head, "Branch head changed; inspect before retrying");
  const commit = await get("https://api.github.com/repos/" + repo + "/git/commits/" + state.head);
  require(commit.tree.sha === state.tree, "Publication state tree differs from remote commit");
  const tree = await get("https://api.github.com/repos/" + repo + "/git/trees/" + state.tree + "?recursive=1");
  require(!tree.truncated, "Remote tree was truncated");
  const remote = Object.fromEntries(tree.tree.filter(x => x.type === "blob").map(x => [x.path, x.sha]));
  let baseline = load("aen_round3_verified_baseline");
  if (!baseline) {
    baseline = {};
    for (let first = 0; first < 11192; first += 2048) {
      const offsets = [];
      for (let i = first; i < Math.min(11192, first + 2048); i += 256) offsets.push(i);
      const pages = await Promise.allSettled(offsets.map(i => py(
        "import json; d=json.load(open('/tmp/aen-r3-baseline.json')); print(json.dumps(list(d['blobs'].items())[" + i + ":" + (i + 256) + "]))")));
      for (const page of pages) {
        if (page.status !== "fulfilled") throw page.reason;
        Object.assign(baseline, Object.fromEntries(JSON.parse(page.value)));
      }
    }
    store("aen_round3_verified_baseline", baseline);
  }
  require(Object.keys(baseline).length === 11192, "Baseline inventory incomplete");
  for (const [path, hash] of Object.entries(baseline)) require(remote[path] === hash, "Baseline blob changed: " + path);
  const addedPaths = Object.keys(remote).filter(path => !(path in baseline));
  require(addedPaths.every(path => path.startsWith(prefix)), "Unexpected new path outside the research round");
  const published = {...state.extra_blobs, ...state.blobs};
  for (const [path, hash] of Object.entries(published)) require(remote[path] === hash, "Published blob differs: " + path);
  const local = JSON.parse(await py(
    "import sys,json,hashlib; from pathlib import Path; sys.path.insert(0," + JSON.stringify(root) + "); " +
    "from experiments.analytic_event_neuron.round3 import freeze; r=Path(" + JSON.stringify(run) + "); f=freeze.verify(r); " +
    "base=Path(" + JSON.stringify(root) + "); " +
    "names=list(f['sources_sha256'])+[" +
      JSON.stringify(prefix + "README.md") + "," + JSON.stringify(prefix + "evidence/ACCEPTANCE.json") + "," +
      JSON.stringify(prefix + "evidence/EVIDENCE_MANIFEST.json") + "," +
      JSON.stringify(prefix + "evidence/results/reviews/FINAL_REPORT_QA.json") + "," +
      JSON.stringify(prefix + "evidence/verify_publication.js") + "]; " +
    "values={p:{'sha256':hashlib.sha256((base/p).read_bytes()).hexdigest(),'git_blob_sha1':hashlib.sha1(b'blob '+str((base/p).stat().st_size).encode()+b'\\0'+(base/p).read_bytes()).hexdigest()} for p in names}; " +
    "print(json.dumps({'files':values,'source_files':len(f['sources_sha256']),'prepared_artifacts':len(f['artifacts_sha256']),'source_commit':f['source_commit'],'freeze_sha256':hashlib.sha256((r/'FREEZE.json').read_bytes()).hexdigest()}))"));
  require(local.source_files === 83 && local.prepared_artifacts === 329, "Frozen inventory incomplete");
  for (const [path, identity] of Object.entries(local.files)) require(remote[path] === identity.git_blob_sha1, "Local/remote artifact differs: " + path);
  const manifest = JSON.parse(await py("from pathlib import Path; print(Path(" + JSON.stringify(root + prefix + "evidence/EVIDENCE_MANIFEST.json") + ").read_text())", 60000));
  require(manifest.archives.length === 37 && manifest.physical_files.length === 79, "Evidence coverage incomplete");
  for (const part of manifest.physical_files) require(remote[part.path] === part.git_blob_sha1, "Archive identity differs: " + part.path);
  const acceptance = JSON.parse(await py("from pathlib import Path; print(Path(" + JSON.stringify(root + prefix + "evidence/ACCEPTANCE.json") + ").read_text())"));
  require(acceptance.production_promotion === false && acceptance.implementation_and_registered_confirmation_complete === true,
          "Unexpected acceptance scope");
  const receipt = {
    schema: "hepta.analytic-event.round3.final-publication-receipt.v1",
    repository: repo, branch: "research/analytic-event-neuron-20261027",
    verified_commit: state.head, verified_tree: state.tree,
    receipt_is_added_in_a_followup_commit: true,
    receipt_itself_is_not_part_of_the_verified_commit: true,
    source_commit: local.source_commit, freeze_sha256: local.freeze_sha256,
    baseline_commit: "ecbfadf12a0347919553220fc0684b16e088347b",
    baseline_blobs_verified_unchanged: 11192,
    added_files_confined_to_round3: true, added_file_count: addedPaths.length,
    published_blob_identities_verified: Object.keys(published).length,
    frozen_source_files_verified_locally_and_remotely: 83,
    frozen_prepared_artifacts_verified_locally: 329,
    logical_archives_verified: 37, physical_archive_blobs_verified: 79,
    compressed_archive_bytes: manifest.summary.compressed_logical_archive_bytes,
    core_artifact_and_source_identities: local.files,
    production_promotion: false, scientific_data_regenerated: false,
    native_inference_or_training_performed: false,
    all_checks_passed: true,
  };
  const encoded = JSON.stringify(JSON.stringify(receipt, null, 2) + "\n");
  await py("from pathlib import Path; data=" + encoded + "; " +
    "Path(" + JSON.stringify(run + "FINAL_PUBLICATION_RECEIPT.json") + ").write_text(data); " +
    "Path(" + JSON.stringify(root + prefix + "evidence/FINAL_PUBLICATION_RECEIPT.json") + ").write_text(data)");
  store("aen_round3_final_verified_tree", remote);
  store("aen_round3_final_receipt", receipt);
  text({verified_commit: state.head, baseline_blobs: 11192, sources: 83, prepared: 329,
        logical_archives: 37, physical_archive_blobs: 79, all_checks_passed: true});
})()
