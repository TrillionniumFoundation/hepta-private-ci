// The Linux browser dependency includes Chromium's terminal-state ordering fix.
// A missing or altered executable is an error; no bundled-browser fallback.
import {resolve} from 'node:path';
import {hashDiagnosticFile,FIXED_BINARY_SHA} from './font-diagnostic-browser-identity.mjs';

const executablePath=process.env.HEPTA_CHROMIUM_EXECUTABLE;
if(process.platform!=='linux'||!executablePath)throw new Error('Install the pinned Linux Chromium and set HEPTA_CHROMIUM_EXECUTABLE');
if(await hashDiagnosticFile(executablePath)!==FIXED_BINARY_SHA)throw new Error('Pinned Chromium executable digest mismatch');
export const pinnedChromiumUse={launchOptions:{executablePath:resolve(executablePath)}};
export const pinnedChromiumMetadata={pinnedChromium:true};
