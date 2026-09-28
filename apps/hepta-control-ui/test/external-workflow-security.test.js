import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const external = readFileSync(`${root}.github/workflows/ui-control-external-qualification.yml`, "utf8");

function section(text, start, end) {
  const from = text.indexOf(start);
  assert.notEqual(from, -1, `missing section ${start}`);
  const to = end ? text.indexOf(end, from + start.length) : text.length;
  assert.notEqual(to, -1, `missing section terminator ${end}`);
  return text.slice(from, to);
}

test("external qualification performs a secretless main-bound repository preflight", () => {
  const input = section(
    external,
    "      repository_qualification_run_id:\n",
    "      run_real_backend:\n",
  );
  assert.match(input, /required:\s*true/u);
  assert.doesNotMatch(input, /default:/u);

  const preflight = section(
    external,
    "  repository-preflight:\n",
    "  candidate-build:\n",
  );
  assert.doesNotMatch(preflight, /\$\{\{\s*secrets\./u);
  assert.doesNotMatch(preflight, /\bnpm\s/u);
  assert.match(preflight, /test "\$WORKFLOW_REF" = refs\/heads\/main/u);
  assert.match(preflight, /ref: \$\{\{ github\.workflow_sha \}\}/u);
  assert.match(preflight, /path: \.ui-control-trusted/u);
  assert.match(preflight, /path: \.ui-control-candidate/u);
  assert.match(preflight, /test "\$\(git -C \.\.\/\.ui-control-trusted rev-parse HEAD\)" = "\$TRUSTED_WORKFLOW_SHA"/u);
  assert.match(preflight, /git merge-base --is-ancestor "\$CANDIDATE_SHA" refs\/remotes\/origin\/main/u);
  assert.match(preflight, /actions\/runs\/\$QUALIFICATION_RUN_ID/u);
  assert.match(preflight, /node \.\.\/\.ui-control-trusted\/qualification\/ui-control\/validate-repository-preflight\.mjs/u);
  assert.match(preflight, /protectedSecretsEligible:\s*false/u);

  const metadata = preflight.indexOf("Fetch official workflow-run metadata");
  const sourceDownload = preflight.indexOf("Download exact-head qualification artifact");
  const semantic = preflight.indexOf("Validate official run metadata and mutually bound exact source/merge receipts");
  assert.ok(metadata >= 0 && sourceDownload > metadata && semantic > sourceDownload);
});

test("candidate-controlled build execution is isolated in a separate secretless job", () => {
  const build = section(
    external,
    "  candidate-build:\n",
    "  protected-external-qualification:\n",
  );
  assert.match(build, /needs:\s*repository-preflight/u);
  assert.match(build, /needs\.repository-preflight\.result == 'success'/u);
  assert.doesNotMatch(build, /environment:/u);
  assert.doesNotMatch(build, /\$\{\{\s*secrets\./u);
  assert.doesNotMatch(build, /\.ui-control-trusted/u);
  assert.match(build, /npm ci --ignore-scripts --no-audit --no-fund/u);
  assert.match(build, /npm run build/u);
  assert.match(build, /git diff --exit-code/u);
  assert.match(build, /git diff --cached --exit-code/u);
  assert.match(build, /name: ui-control-candidate-build-\$\{\{ inputs\.candidate_sha \}\}/u);
});

test("the protected job uses a fresh runner and executes only immutable trusted verifiers", () => {
  const job = section(external, "  protected-external-qualification:\n");
  assert.match(job, /needs: \[repository-preflight, candidate-build\]/u);
  assert.match(job, /needs\.repository-preflight\.result == 'success' && needs\.candidate-build\.result == 'success'/u);
  assert.match(job, /environment:\s*ui-control-production-qualification/u);
  assert.match(job, /ref: \$\{\{ github\.workflow_sha \}\}/u);
  assert.match(job, /path: \.ui-control-trusted/u);
  assert.match(job, /path: \.ui-control-candidate/u);
  assert.match(job, /non-executable subject data/u);
  assert.match(job, /test "\$\(git -C \.\.\/\.ui-control-trusted rev-parse HEAD\)" = "\$TRUSTED_WORKFLOW_SHA"/u);
  assert.match(job, /git merge-base --is-ancestor "\$CANDIDATE_SHA" refs\/remotes\/origin\/main/u);
  assert.doesNotMatch(job, /\bnpm\s/u);

  const artifactDownload = job.indexOf("Download isolated candidate build as untrusted data");
  const artifactValidation = job.indexOf("Validate the complete candidate build artifact with the trusted verifier");
  const firstSecret = job.indexOf("${{ secrets.");
  assert.ok(artifactDownload >= 0 && artifactValidation > artifactDownload && firstSecret > artifactValidation);

  const preSecret = job.slice(0, firstSecret);
  assert.match(preSecret, /candidate-build-artifact\.mjs/u);
  assert.match(preSecret, /UI_CONTROL_PROTECTED_SOURCE_HEAD_RECEIPT/u);
  assert.match(preSecret, /candidate-build-observation\.json/u);

  const protectedTail = job.slice(firstSecret);
  assert.match(protectedTail, /HEPTA_UI_CONTROL_BUILD_MANIFEST: \.\.\/ui-control-candidate-build\/build-manifest\.json/u);
  assert.match(protectedTail, /node \.\.\/\.ui-control-trusted\/qualification\/ui-control\/deployment-security\.mjs/u);
  assert.match(protectedTail, /node \.\.\/\.ui-control-trusted\/qualification\/ui-control\/real-backend-contract\.mjs/u);
  assert.match(protectedTail, /node \.\.\/\.ui-control-trusted\/qualification\/ui-control\/validate-external-evidence\.mjs/u);
  assert.doesNotMatch(protectedTail, /run:\s*node qualification\/ui-control\//u);
  assert.match(job, /HEPTA_UI_CONTROL_ALLOW_MUTATION: I_UNDERSTAND_THIS_USES_A_DISPOSABLE_QUALIFICATION_TARGET/u);
  assert.match(job, /if: \$\{\{ inputs\.run_production_evidence \}\}/u);
});
