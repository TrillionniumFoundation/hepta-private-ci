import { withArtifactLease, loadArtifactSnapshot } from '../tools/owned-artifact-lease.mjs';

const [, , root, dist] = process.argv;
const snapshot = await withArtifactLease(root, 'preview', () => loadArtifactSnapshot(dist));
console.log(snapshot.buffers.get('index.html').toString());
