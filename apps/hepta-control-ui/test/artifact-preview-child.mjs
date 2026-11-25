import { createServer } from 'node:http';
import { writeFileSync } from 'node:fs';
import { withArtifactLease, loadArtifactSnapshot } from '../tools/owned-artifact-lease.mjs';

const [, , root, dist, marker] = process.argv;
const snapshot = await withArtifactLease(root, 'preview', () => loadArtifactSnapshot(dist));
const server = createServer((req, res) => res.end(snapshot.buffers.get('index.html')));
server.listen(0, '127.0.0.1', () => writeFileSync(marker, String(server.address().port)));
