// Exact SDK version and transitive integrity are pinned in package-lock.json.
import fs from 'node:fs';
import path from 'node:path';
import artifact from '@actions/artifact';

const [requestFile, responseFile] = process.argv.slice(2);
let phase = 'request';
try {
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('Node24Required');
  const request = JSON.parse(fs.readFileSync(requestFile, 'utf8'));
  if (!process.env.ACTIONS_RUNTIME_TOKEN || !process.env.ACTIONS_RESULTS_URL) {
    throw new Error('MissingActionsRuntime');
  }
  let result;
  phase = request.operation;
  if (phase === 'upload') {
    const uploaded = await artifact.uploadArtifact(request.name, request.files, request.root,
      {compressionLevel: 0, retentionDays: 90});
    if (!Number.isSafeInteger(uploaded.id) || uploaded.id <= 0 ||
        !Number.isSafeInteger(uploaded.size) || uploaded.size <= 0 ||
        !/^[0-9a-f]{64}$/.test(uploaded.digest ?? '')) throw new Error('InvalidUploadResponse');
    result = {id: uploaded.id, name: request.name, bytes: uploaded.size,
      sha256: uploaded.digest, sdk: '@actions/artifact@6.2.0', node: process.version,
      requested_retention_days: 90};
  } else if (phase === 'download') {
    if (fs.readdirSync(request.destination).length !== 0) throw new Error('NonemptyDownloadDirectory');
    const downloaded = await artifact.downloadArtifact(request.id,
      {path: request.destination, expectedHash: `sha256:${request.sha256}`, skipDecompress: true});
    if (downloaded.digestMismatch !== false ||
        path.resolve(downloaded.downloadPath) !== path.resolve(request.destination)) {
      throw new Error('DownloadDigestOrDestinationMismatch');
    }
    result = {id: request.id, expected_sha256: request.sha256, digest_mismatch: false,
      raw_archive: true, sdk: '@actions/artifact@6.2.0'};
  } else throw new Error('UnknownOperation');
  fs.writeFileSync(responseFile, JSON.stringify({ok: true, operation: phase, result}) + '\n', {flag: 'wx'});
} catch (error) {
  // Never serialize SDK error messages, URLs, headers, request objects or tokens.
  fs.writeFileSync(responseFile, JSON.stringify({ok: false, operation: phase,
    error_type: /^[A-Za-z0-9_]{1,80}$/.test(error?.name ?? '') ? error.name : 'Error'}) + '\n', {flag: 'wx'});
  process.exitCode = 1;
}
