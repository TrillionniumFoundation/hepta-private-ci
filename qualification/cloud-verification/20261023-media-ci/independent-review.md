# Independent dedicated codec CI review

No blocking finding in final three-file source set. Base #3563 `a88f2832f2a1a4d3734c1c88f76977dcc9b98ff1`. Full diff SHA256 `3b2bccb75faddac2a23c45a908de4864b8d69057c631aa70f5de2a9789ebaadd`; tree `b9c7da14102e0e7ab5b611859e58bb8701e3c91a`. Per-file hashes in independent-review-manifest.json. Source files unchanged by reviewer; temporary index used solely for complete diff/tree including new files.

## Contract and fix

Existing 21 media tests use class skipUnless for ffmpeg/ffprobe, explicitly saying dedicated CI enforces tools. Keeping these generic skips is intentional compatibility for lightweight environments. The dedicated workflow previously relied on selected runner image and piped version commands into head, then ordinary unittest discovery, which accepts all-skipped suites. Parent supplied historical job120450755349 evidence; reviewer independently reproduced the all-skip success locally, rather than claiming to have independently fetched historical CI logs.

The updated workflow installs ffmpeg through existing Ubuntu apt sources, without adding a custom repository or changing workflow permissions. Explicit bash and standalone command-v/version commands eliminate upstream-pipeline masking. Exact pull-request HEAD checkout/assertion, persist-credentials=false, contents:read, ubuntu24.04 and timeout remain. New runner/self-test paths are included in PR triggers. compileall, six gate self-tests, mandatory codec acceptance, full regression and unchanged SHADOW_ONLY/manifest denial assertions are all sequential required steps; no continue-on-error or permissive fallback added. Package installation/network availability must still be observed on the actual hosted runner; local success is not that evidence.

run_codec_acceptance checks both executable resolutions and runs each version command without shell, check=True and timeout30. Missing tools, execution error, timeout or nonzero exit return1 before discovery. Discovery remains the exact existing test_*media*.py pattern. Zero tests, any skipped test, expectedFailures, test failures/errors and unexpected successes cannot return accepted0 (wasSuccessful plus explicit predicates). This ensures a successful dedicated acceptance includes executed media tests, not merely successful imports or syntactic checks. It does not certify arbitrary binaries on PATH; actual decode tests provide functional fixture coverage.

All previous media test decorators, implementation/scoring rules, signature fixtures and manifest scope statements remain unchanged. The runner does not modify credentials, invoke models or authorize deployment. Non-media tests in the broad follow-up discovery retain normal unittest semantics; the no-skip requirement is specifically enforced on the media acceptance suite.

## Independent execution

- `python3 -m unittest discover -s qualification/ndu-dmgp-shadow -p test_codec_acceptance.py -v`: 6 passed; independent-gate-tests.log. Covers actual entrypoint missing-tools process exit, either missing tool, nonzero version, empty/all-skipped/partially-skipped suites, failed test, and successful execution.
- `python3 qualification/ndu-dmgp-shadow/run_codec_acceptance.py`: 21 passed, skipped0, accepted=True using existing real local FFmpeg/ffprobe; independent-codec-acceptance.log (14.727s).
- Fresh child processes with PATH pointing at an empty temporary directory: generic media discovery exits0 with 21 skipped, while actual acceptance entrypoint exits1 with required ffmpeg unavailable. Full command outputs preserved in independent-missing-tools.log. This directly verifies the intended distinction without changing general skip behavior.

The latest workflow additions (compileall and full regression step) were independently inspected after these test runs; runner/test content remained unchanged. No full107-suite result or hosted CI pass is claimed by this reviewer. Parent owns exact-source full regression, remote file checks and CI follow-up.

## Scope

No remaining blocker for source publication as a draft. This closes a dedicated CI false-green path; successful fixture decoding is structural codec evidence, not real trained-model quality, semantic truth, independent real outcomes, hardware/energy efficiency, six-blocker scientific closure, authority admission or permission to merge/deploy. Those denials remain explicit in workflow and existing manifest.

Final freeze follow-up: parent source-manifest.json matches all independently computed hashes exactly. Independently inspected parent full-tests.txt completion: 107 tests, OK, no skip summary (27.534s). This updates full-suite evidence to parent-executed success; hosted exact-source CI remains pending. Only the three listed source files belong to this source publication; evidence README is separate.

Complete final SHA256 mapping:

- .github/workflows/hepta-ndu-dmgp-decoded-media.yml: `2a338fa463806eb89540c22f17ee95668ba8df1c09c7e15e0eff2006be39fb4d`
- qualification/ndu-dmgp-shadow/run_codec_acceptance.py: `9e98fd63845da16eed5aed1401c6de22ab3ee010f413eb5f79362be32d2b1f6a`
- qualification/ndu-dmgp-shadow/test_codec_acceptance.py: `28cd1537a78f4e5554be42d3adb60f23a8cf9343febb36fa63de257684df3b17`
