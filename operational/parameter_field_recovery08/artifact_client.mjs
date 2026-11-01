// Exact SDK version and transitive integrity are pinned in package-lock.json.
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';

const [requestFile, responseFile] = process.argv.slice(2);
let phase = 'request';
try {
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('Node24Required');
  const request = JSON.parse(fs.readFileSync(requestFile, 'utf8'));
  if (!process.env.ACTIONS_RUNTIME_TOKEN || !process.env.ACTIONS_RESULTS_URL) {
    throw new Error('MissingActionsRuntime');
  }
  phase = 'sdk-validation';
  const source = path.dirname(fileURLToPath(import.meta.url));
  const root = process.env.HEPTA_ARTIFACT_SDK_ROOT || source;
  if (!path.isAbsolute(root) || fs.realpathSync(root) !== root) throw new Error('NoncanonicalSdkRoot');
  const sdkSource = {root, metadata: {}};
  for (const name of ['package.json', 'package-lock.json']) {
    const declared = fs.readFileSync(path.join(source, name));
    const installed = fs.readFileSync(path.join(root, name));
    if (!declared.equals(installed)) throw new Error('SdkMetadataBytesDiffer');
    sdkSource.metadata[name] = {bytes: installed.length, sha256: createHash('sha256').update(installed).digest('hex')};
  }
  const declared = JSON.parse(fs.readFileSync(path.join(root, 'package.json')));
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json')));
  const installed = JSON.parse(fs.readFileSync(path.join(root, 'node_modules/@actions/artifact/package.json')));
  if (declared.dependencies?.['@actions/artifact'] !== '6.2.0' ||
      lock.packages?.['node_modules/@actions/artifact']?.version !== '6.2.0' ||
      installed.name !== '@actions/artifact' || installed.version !== '6.2.0' ||
      installed.exports?.['.']?.import !== './lib/artifact.js') throw new Error('SdkIdentityMismatch');
  // This pinned SDK publishes an import-only export. Resolve its verified entry
  // explicitly, then use ESM import rather than pretending it has a require export.
  const resolve = createRequire(path.join(root, 'package.json'));
  const entry = resolve.resolve('./node_modules/@actions/artifact/lib/artifact.js');
  if (!fs.realpathSync(entry).startsWith(root + path.sep)) throw new Error('SdkEntryEscapedRoot');
  sdkSource.entry_sha256 = createHash('sha256').update(fs.readFileSync(entry)).digest('hex');
  const {default: artifact} = await import(pathToFileURL(entry).href);
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
      sdk_source: sdkSource, requested_retention_days: 90};
  } else if (phase === 'download') {
    if (fs.readdirSync(request.destination).length !== 0) throw new Error('NonemptyDownloadDirectory');
    const downloaded = await artifact.downloadArtifact(request.id,
      {path: request.destination, expectedHash: `sha256:${request.sha256}`, skipDecompress: true});
    if (downloaded.digestMismatch !== false ||
        path.resolve(downloaded.downloadPath) !== path.resolve(request.destination)) {
      throw new Error('DownloadDigestOrDestinationMismatch');
    }
    result = {id: request.id, expected_sha256: request.sha256, digest_mismatch: false,
      raw_archive: true, sdk: '@actions/artifact@6.2.0', sdk_source: sdkSource};
  } else throw new Error('UnknownOperation');
  fs.writeFileSync(responseFile, JSON.stringify({ok: true, operation: phase, result}) + '\n', {flag: 'wx'});
} catch (error) {
  // Never serialize SDK error messages, URLs, headers, request objects or tokens.
  fs.writeFileSync(responseFile, JSON.stringify({ok: false, operation: phase,
    error_type: /^[A-Za-z0-9_]{1,80}$/.test(error?.name ?? '') ? error.name : 'Error'}) + '\n', {flag: 'wx'});
  process.exitCode = 1;
}
