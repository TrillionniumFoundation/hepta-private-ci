import {
  assertEvidence,
  boundedText,
  sha256,
} from "./external-evidence-primitives.mjs";

const APPROVAL_ROLES = Object.freeze([
  "deployment-authority",
  "release-authority",
  "security-authority",
]);
const PRINCIPAL_DIGEST_DOMAIN = "hepta.ui-control.assurance-principal.v1";

function canonicalPrincipal(value, label) {
  return boundedText(value, label, 256).normalize("NFKC").toLowerCase();
}

function digestPrincipal(principal) {
  return sha256(Buffer.from(`${PRINCIPAL_DIGEST_DOMAIN}\0${principal}`, "utf8"));
}

function normalizedTimestamp(value, label) {
  const timestamp = Date.parse(value);
  assertEvidence(
    Number.isFinite(timestamp),
    "UI_CONTROL_ASSURANCE_TIME",
    `${label} is not a valid timestamp`,
  );
  return Object.freeze({
    timestamp,
    iso: new Date(timestamp).toISOString(),
  });
}

export function validateAssuranceChain(receipts) {
  assertEvidence(
    receipts && typeof receipts === "object" && !Array.isArray(receipts),
    "UI_CONTROL_ASSURANCE_OBJECT",
    "assurance-chain receipts must be an object",
  );

  const acceptancePrincipal = canonicalPrincipal(
    receipts.independentAcceptanceReceipt?.verifier?.identity,
    "independentAcceptance.verifier.identity",
  );
  const securityPrincipal = canonicalPrincipal(
    receipts.independentSecurityReceipt?.reviewer?.identity,
    "independentSecurity.reviewer.identity",
  );
  assertEvidence(
    acceptancePrincipal !== securityPrincipal,
    "UI_CONTROL_ASSURANCE_IDENTITY_REUSE",
    "independent acceptance and independent security review reused one principal",
  );

  const approvals = receipts.productionApprovalReceipt?.approvals;
  assertEvidence(
    Array.isArray(approvals) && approvals.length === APPROVAL_ROLES.length,
    "UI_CONTROL_ASSURANCE_APPROVALS",
    "assurance chain requires exactly the three production approval roles",
  );
  const approvalPrincipals = new Map();
  const approvalTimes = new Map();
  const observedPrincipals = new Set();
  for (const approval of approvals) {
    const role = boundedText(approval?.role, "approval.role", 96);
    assertEvidence(
      APPROVAL_ROLES.includes(role) && !approvalPrincipals.has(role),
      "UI_CONTROL_ASSURANCE_APPROVAL_ROLE",
      `unexpected or duplicate production approval role: ${role}`,
    );
    const principal = canonicalPrincipal(approval?.identity, `${role}.identity`);
    assertEvidence(
      !observedPrincipals.has(principal),
      "UI_CONTROL_ASSURANCE_IDENTITY_REUSE",
      "production approval roles reused one principal",
    );
    assertEvidence(
      principal !== acceptancePrincipal && principal !== securityPrincipal,
      "UI_CONTROL_ASSURANCE_IDENTITY_REUSE",
      "an independent reviewer was reused as a production approval authority",
    );
    approvalPrincipals.set(role, principal);
    approvalTimes.set(
      role,
      normalizedTimestamp(approval?.approvedAt, `${role}.approvedAt`),
    );
    observedPrincipals.add(principal);
  }
  assertEvidence(
    APPROVAL_ROLES.every(role => approvalPrincipals.has(role)),
    "UI_CONTROL_ASSURANCE_APPROVAL_ROLE",
    "one or more production approval roles are missing",
  );

  const timeline = Object.freeze({
    deploymentSecurityObservedAt: normalizedTimestamp(
      receipts.deploymentSecurityReceipt?.deployment?.observedAt,
      "deploymentSecurity.deployment.observedAt",
    ),
    realBackendObservedAt: normalizedTimestamp(
      receipts.realBackendReceipt?.backend?.observedAt,
      "realBackend.backend.observedAt",
    ),
    independentAcceptanceExecutedAt: normalizedTimestamp(
      receipts.independentAcceptanceReceipt?.executedAt,
      "independentAcceptance.executedAt",
    ),
    independentSecurityExecutedAt: normalizedTimestamp(
      receipts.independentSecurityReceipt?.executedAt,
      "independentSecurity.executedAt",
    ),
    operationalExerciseExecutedAt: normalizedTimestamp(
      receipts.operationalExerciseReceipt?.executedAt,
      "operationalExercise.executedAt",
    ),
    productionApprovedAt: normalizedTimestamp(
      receipts.productionApprovalReceipt?.approvedAt,
      "productionApproval.approvedAt",
    ),
  });
  const prerequisiteTimeline = Object.entries(timeline)
    .filter(([name]) => name !== "productionApprovedAt");
  for (const [name, evidence] of prerequisiteTimeline) {
    assertEvidence(
      timeline.productionApprovedAt.timestamp >= evidence.timestamp,
      "UI_CONTROL_APPROVAL_PREMATURE",
      `production approval predates accepted evidence: ${name}`,
    );
  }
  for (const [role, approvalTime] of approvalTimes) {
    for (const [name, evidence] of prerequisiteTimeline) {
      assertEvidence(
        approvalTime.timestamp >= evidence.timestamp,
        "UI_CONTROL_APPROVAL_PREMATURE",
        `${role} approval predates accepted evidence: ${name}`,
      );
    }
    assertEvidence(
      approvalTime.timestamp <= timeline.productionApprovedAt.timestamp,
      "UI_CONTROL_APPROVAL_AFTER_SUMMARY",
      `${role} approval is later than productionApproval.approvedAt`,
    );
  }
  const latestApproval = Math.max(
    ...[...approvalTimes.values()].map(value => value.timestamp),
  );
  assertEvidence(
    timeline.productionApprovedAt.timestamp === latestApproval,
    "UI_CONTROL_APPROVAL_SUMMARY_TIME",
    "productionApproval.approvedAt must equal the latest individual authority approval",
  );

  return Object.freeze({
    schema: "hepta.ui-control.assurance-chain.v1",
    principalCount: APPROVAL_ROLES.length + 2,
    reviewerIdentityDigests: Object.freeze({
      independentAcceptance: digestPrincipal(acceptancePrincipal),
      independentSecurity: digestPrincipal(securityPrincipal),
    }),
    approvalIdentityDigests: Object.freeze(Object.fromEntries(
      APPROVAL_ROLES.map(role => [role, digestPrincipal(approvalPrincipals.get(role))]),
    )),
    evidenceTimeline: Object.freeze(Object.fromEntries(
      Object.entries(timeline).map(([name, value]) => [name, value.iso]),
    )),
    reviewerSeparationVerified: true,
    evidenceChronologyBound: true,
  });
}
