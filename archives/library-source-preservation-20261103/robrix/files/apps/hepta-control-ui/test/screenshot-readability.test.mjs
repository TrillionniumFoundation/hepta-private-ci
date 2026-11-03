import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {readScreenshotText,requireChatText} from '../tools/verify-robrix-pixels.mjs';
test('real Chromium glyph-block failure cannot pass chat readability',async()=>{
 const path=fileURLToPath(new URL('./fixtures/robrix-render/unreadable-e51a1d0f.png',import.meta.url));
 const text=await readScreenshotText(path);
 assert.throws(()=>requireChatText(text),/Actual canvas screenshot/);
});
