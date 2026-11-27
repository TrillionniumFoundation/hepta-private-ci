import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";

import { describe, it } from "@jest/globals";

import { codexExecPath } from "./testCodex";

const conformanceTimeoutMs = 300_000;
const reviewerRegressionTimeoutMs = 180_000;

function requireFile(filePath: string, description: string): string {
  if (!existsSync(filePath)) {
    throw new Error(`MCP conformance ${description} does not exist: ${filePath}`);
  }

  return filePath;
}

function conformanceDirectory(): string {
  const repositoryRoot = path.resolve(process.cwd(), "../..");
  const candidates = [
    path.join(repositoryRoot, "public", "scripts", "mcp_conformance"),
    path.join(repositoryRoot, "scripts", "mcp_conformance"),
  ];

  for (const candidate of candidates) {
    if (existsSync(path.join(candidate, "run_codex_compliance.py"))) {
      return candidate;
    }
  }

  throw new Error(`MCP conformance harness is missing; checked ${candidates.join(" and ")}`);
}

function verifyReviewerIdentity(
  directory: string,
  codexBinary: string,
  fixtureReceipt: string,
  phase: "before-reviewer" | "after-reviewer",
  deadline: number,
): void {
  const remaining = Math.floor(deadline - performance.now());
  if (remaining <= 0) {
    throw new Error("MCP reviewer identity exhausted the original reviewer deadline.");
  }
  const result = spawnSync(
    "python3",
    [
      path.join(directory, "prepare_oauth_fixture.py"),
      "--verify-sdk-use",
      phase,
      "--fixture-receipt",
      fixtureReceipt,
      "--codex-binary",
      codexBinary,
    ],
    { encoding: "utf8", maxBuffer: 16 * 1024 * 1024, timeout: remaining },
  );
  if (result.error || result.status !== 0 || performance.now() > deadline) {
    throw new Error(
      [
        `MCP reviewer ${phase} identity failed: ${result.status ?? result.signal}.`,
        result.error?.message,
        result.stdout,
        result.stderr,
      ]
        .filter(Boolean)
        .join("\n"),
      { cause: result.error },
    );
  }
}

describe("MCP client conformance", () => {
  it(
    "does not introduce shipping, intermediate, or modern official conformance regressions",
    () => {
      const directory = conformanceDirectory();
      const receiptLocation = process.env.CODEX_MCP_CONFORMANCE_FIXTURE_RECEIPT;
      if (!receiptLocation) {
        throw new Error(
          "Build the reviewed OAuth-origin conformance fixture and set CODEX_MCP_CONFORMANCE_FIXTURE_RECEIPT.",
        );
      }
      const fixtureReceipt = requireFile(path.resolve(receiptLocation), "reviewed fixture receipt");
      const officialConformanceCli = requireFile(
        path.join(path.dirname(fixtureReceipt), "upstream", "dist", "index.js"),
        "reviewed upstream fixture CLI",
      );
      const codexBinary = requireFile(codexExecPath, "built Codex binary");
      const baseline = requireFile(
        path.join(directory, "regression-baseline-v1.json"),
        "committed regression baseline",
      );
      const reportDirectory = process.env.RUNNER_TEMP ?? os.tmpdir();
      const reportPath = path.join(reportDirectory, `codex-mcp-conformance-${process.pid}.json`);
      const result = spawnSync(
        "python3",
        [
          path.join(directory, "run_codex_compliance.py"),
          codexBinary,
          "--mode",
          "all",
          "--transport",
          "all",
          "--auth",
          "--conformance-cli",
          officialConformanceCli,
          "--conformance-fixture-receipt",
          fixtureReceipt,
          "--baseline-report",
          baseline,
          "--report",
          reportPath,
        ],
        {
          encoding: "utf8",
          maxBuffer: 16 * 1024 * 1024,
          timeout: conformanceTimeoutMs - 10_000,
        },
      );

      if (result.error) {
        throw new Error(`MCP conformance runner could not complete: ${result.error.message}`, {
          cause: result.error,
        });
      }

      if (result.status !== 0) {
        throw new Error(
          [
            `MCP conformance regression gate exited with ${result.status ?? result.signal}.`,
            `Report: ${reportPath}`,
            result.stdout,
            result.stderr,
          ]
            .filter(Boolean)
            .join("\n"),
        );
      }
    },
    conformanceTimeoutMs,
  );

  it(
    "does not introduce production reviewer or catalog-boundary regressions",
    () => {
      const directory = conformanceDirectory();
      const codexBinary = requireFile(codexExecPath, "built Codex binary");
      const receiptLocation = process.env.CODEX_MCP_CONFORMANCE_FIXTURE_RECEIPT;
      if (!receiptLocation) {
        throw new Error("The reviewer requires this original SDK fixture receipt.");
      }
      const fixtureReceipt = requireFile(path.resolve(receiptLocation), "reviewed fixture receipt");
      const deadline = performance.now() + reviewerRegressionTimeoutMs - 10_000;
      const reviewer = requireFile(
        path.join(directory, "review_regressions.py"),
        "production reviewer regression runner",
      );
      const baseline = requireFile(
        path.join(directory, "review-regression-baseline-v1.json"),
        "committed production reviewer regression baseline",
      );
      const reportDirectory = process.env.RUNNER_TEMP ?? os.tmpdir();
      const reportPath = path.join(reportDirectory, `codex-mcp-review-${process.pid}.json`);
      verifyReviewerIdentity(directory, codexBinary, fixtureReceipt, "before-reviewer", deadline);
      const failures: unknown[] = [];
      try {
        if (performance.now() >= deadline) {
          throw new Error("MCP reviewer exhausted the original deadline before execution.");
        }
        const result = spawnSync(
          "python3",
          [
            reviewer,
            codexBinary,
            "--mode",
            "all",
            "--baseline-report",
            baseline,
            "--report",
            reportPath,
          ],
          {
            encoding: "utf8",
            maxBuffer: 16 * 1024 * 1024,
            timeout: Math.max(1, Math.floor(deadline - performance.now())),
          },
        );

        if (result.error) {
          throw new Error(
            `MCP production reviewer regression runner could not complete: ${result.error.message}`,
            { cause: result.error },
          );
        }

        if (result.status !== 0) {
          throw new Error(
            [
              `MCP production reviewer regression gate exited with ${result.status ?? result.signal}.`,
              `Report: ${reportPath}`,
              result.stdout,
              result.stderr,
            ]
              .filter(Boolean)
              .join("\n"),
          );
        }
      } catch (error) {
        failures.push(error);
      }
      try {
        verifyReviewerIdentity(directory, codexBinary, fixtureReceipt, "after-reviewer", deadline);
      } catch (identityError) {
        failures.push(identityError);
      }
      if (failures.length > 1) {
        throw new AggregateError(
          failures,
          "MCP reviewer and its final identity observation both failed.",
        );
      }
      if (failures.length === 1) {
        throw failures[0];
      }
    },
    reviewerRegressionTimeoutMs,
  );
});
