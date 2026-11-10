(() => {
  const root = '/workspace/scratch/c385a7439f8e';
  const repoPath = root + '/hcsn-repo';
  const repository = 'TrillionniumFoundation/hepta-private-ci';
  const branch = 'codex/hcsn-current-resources-api-20261110-c385';
  const sq = s => "'" + s.replace(/'/g, "'\\''") + "'";
  function doc(r) {
    if (r.isError) throw Error(JSON.stringify(r));
    const s = r.structuredContent;
    if (typeof s?.content === 'string') return JSON.parse(s.content);
    if (s) return s;
    throw Error('Missing structured GitHub response');
  }
  async function py(script, args = []) {
    const r = await tools.exec_command({
      cmd: 'python -c ' + sq(script) + args.map(s => ' ' + sq(typeof s === 'string' ? s : JSON.stringify(s))).join(''),
      workdir: repoPath, max_output_tokens: 100000,
    });
    if (r.exit_code !== 0) throw Error(r.output);
    return JSON.parse(r.output);
  }
  async function readJson(path) {
    return py('import pathlib,json,sys\nprint(pathlib.Path(sys.argv[1]).read_text())', [path]);
  }
  async function writeJson(path, value) {
    const data = JSON.stringify(value, null, 2) + '\n';
    await py('import pathlib,sys,json\np=pathlib.Path(sys.argv[1]+".pending");p.write_text("");print("true")', [path]);
    for (let i = 0; i < data.length; i += 32768) {
      await py('import pathlib,sys,json\np=pathlib.Path(sys.argv[1]+".pending")\nwith p.open("a") as f:f.write(sys.argv[2])\nprint("true")', [path, data.slice(i, i + 32768)]);
    }
    await py('import pathlib,sys,json\np=pathlib.Path(sys.argv[1]+".pending");json.loads(p.read_text());p.replace(sys.argv[1]);print("true")', [path]);
  }
  async function upload() {
    const files = await readJson(root + '/evidence-current-binary-files.json');
    const progress = await readJson(root + '/hcsn-evidence-binary-upload-progress.json');
    const records = progress.records;
    for (const f of files) {
      if (records.some(r => r.path === f.path && r.remote_sha === f.git_blob_sha && r.sha256 === f.sha256)) continue;
      const known = records.find(r => r.remote_sha === f.git_blob_sha && r.sha256 === f.sha256);
      let remoteSha;
      if (known) remoteSha = known.remote_sha;
      else {
        const chunks = [];
        for (let offset = 0; offset < f.bytes; offset += 49152) {
          chunks.push(await py('import pathlib,base64,json,sys\np=pathlib.Path(sys.argv[1]);o=int(sys.argv[2]);print(json.dumps(base64.b64encode(p.read_bytes()[o:o+49152]).decode()))', [f.absolute_path, String(offset)]));
        }
        const content = chunks.join('');
        if (content.length !== Math.ceil(f.bytes / 3) * 4) throw Error('Base64 length mismatch: ' + f.path);
        remoteSha = doc(await tools.mcp__codex_apps__github_create_blob({ repository_full_name: repository, encoding: 'base64', content })).sha;
        if (remoteSha !== f.git_blob_sha) throw Error('Binary Git hash mismatch: ' + f.path);
      }
      records.push({ ...f, remote_sha: remoteSha, verified: true, object_reused: Boolean(known) });
      progress.observed_utc = new Date().toISOString();
      await writeJson(root + '/hcsn-evidence-binary-upload-progress.json', progress);
      notify({ binary: f.path, bytes: f.bytes, verified: true });
    }
    return { current_paths: files.length, all_verified: files.every(f => records.some(r => r.path === f.path && r.remote_sha === f.git_blob_sha && r.sha256 === f.sha256)) };
  }
  async function publish() {
    const stages = await readJson(root + '/hcsn-current-resources-local-stages-v1.json');
    const progress = await readJson(root + '/hcsn-current-resources-api-progress-v1.json');
    const binary = (await readJson(root + '/hcsn-evidence-binary-upload-progress.json')).records;
    const records = progress.records;
    const current = doc(await tools.mcp__codex_apps__github_fetch({ url: 'https://api.github.com/repos/' + repository + '/git/ref/heads/' + branch }));
    const observedHead = current.object.sha;
    const knownHeads = ['14e8427f46d6517d8d57649b8ac0b888b1c991e8', ...records.map(r => r.remote_commit)];
    if (!knownHeads.includes(observedHead)) throw Error('Unexpected remote branch head; no overwrite');
    for (const stage of stages) {
      if (records.some(r => r.local_commit === stage.local_commit)) continue;
      const prior = records[records.length - 1];
      const parent = prior ? prior.remote_commit : '14e8427f46d6517d8d57649b8ac0b888b1c991e8';
      let tree = prior ? prior.tree : 'da62f605dfa9771c439d0f91edf3deff5aed7818';
      const files = await py('import subprocess,sys,json,hashlib\na,b=sys.argv[1:3];rows=[]\nfor line in subprocess.check_output(["git","diff","--name-status",a,b],text=True).splitlines():\n s,n=line.split("\\t");assert s in ["A","M","D"]\n if s=="D":rows.append({"path":n,"delete":True});continue\n line=subprocess.check_output(["git","ls-tree",b,"--",n],text=True);info,_=line.split("\\t",1);mode,kind,sha=info.split();assert kind=="blob"\n data=subprocess.check_output(["git","cat-file","blob",sha]);binary=b"\\0" in data\n try:data.decode("utf-8")\n except UnicodeDecodeError:binary=True\n rows.append({"path":n,"mode":mode,"git_blob_sha":sha,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"binary":binary})\nprint(json.dumps(rows))', [stage.local_parent, stage.local_commit]);
      let batch = [], size = 0;
      async function flush() {
        if (!batch.length) return;
        tree = doc(await tools.mcp__codex_apps__github_create_tree({ repository_full_name: repository, base_tree_sha: tree, tree_elements: batch })).sha;
        batch = []; size = 0;
      }
      for (const f of files) {
        let element;
        if (f.delete) element = { path: f.path, mode: '100644', type: 'blob', sha: null };
        else if (f.binary) {
          if (!binary.some(r => r.remote_sha === f.git_blob_sha && r.sha256 === f.sha256)) throw Error('Unuploaded binary: ' + f.path);
          element = { path: f.path, mode: f.mode, type: 'blob', sha: f.git_blob_sha };
        } else if (f.bytes > 32768) {
          const chunks = [];
          for (let o = 0; ; o += 32768) {
            const chunk = await py('import subprocess,json,sys\ns=subprocess.check_output(["git","cat-file","blob",sys.argv[1]]).decode("utf-8");o=int(sys.argv[2]);print(json.dumps(s[o:o+32768]))', [f.git_blob_sha, String(o)]);
            chunks.push(chunk); if (chunk.length < 32768) break;
          }
          const blob = doc(await tools.mcp__codex_apps__github_create_blob({ repository_full_name: repository, encoding: 'utf-8', content: chunks.join('') }));
          if (blob.sha !== f.git_blob_sha) throw Error('Text Git hash mismatch: ' + f.path);
          element = { path: f.path, mode: f.mode, type: 'blob', sha: blob.sha };
        } else {
          const content = await py('import subprocess,json,sys\nprint(json.dumps(subprocess.check_output(["git","cat-file","blob",sys.argv[1]]).decode("utf-8")))', [f.git_blob_sha]);
          element = { path: f.path, mode: f.mode, type: 'blob', content };
        }
        const count = JSON.stringify(element).length;
        if (size + count > 24000) await flush();
        batch.push(element); size += count;
      }
      await flush();
      if (tree !== stage.tree) throw Error('Whole tree mismatch: ' + stage.local_commit);
      const commit = doc(await tools.mcp__codex_apps__github_create_commit({ repository_full_name: repository, parent_sha: parent, tree_sha: tree, message: stage.message }));
      const readback = doc(await tools.mcp__codex_apps__github_fetch({ url: 'https://api.github.com/repos/' + repository + '/git/commits/' + commit.sha }));
      if (readback.tree.sha !== tree) throw Error('Commit readback mismatch');
      records.push({ local_commit: stage.local_commit, local_parent: stage.local_parent, remote_parent: parent, remote_commit: commit.sha, tree, files, full_tree_identical: true });
      progress.observed_utc = new Date().toISOString();
      await writeJson(root + '/hcsn-current-resources-api-progress-v1.json', progress);
      notify({ local_commit: stage.local_commit, remote_commit: commit.sha, tree, files: files.length, verified: true });
    }
    const last = records[records.length - 1];
    if (observedHead !== last.remote_commit) {
      doc(await tools.mcp__codex_apps__github_update_ref({ repository_full_name: repository, branch_name: branch, sha: last.remote_commit, expected_sha: observedHead, force: false }));
    }
    const checked = doc(await tools.mcp__codex_apps__github_fetch({ url: 'https://api.github.com/repos/' + repository + '/git/ref/heads/' + branch }));
    if (checked.object.sha !== last.remote_commit) throw Error('Branch readback mismatch');
    return { stages: records.length, branch, remote_head: last.remote_commit, tree: last.tree, verified: true };
  }
  return { upload, publish };
})()
