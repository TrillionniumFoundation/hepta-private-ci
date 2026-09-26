export const UI_CONTROL_ERROR_CODES = Object.freeze({
  INVALID_INPUT: "UI_CONTROL_INVALID_INPUT",
  NOT_CONNECTED: "UI_CONTROL_NOT_CONNECTED",
  SESSION_EXPIRED: "UI_CONTROL_SESSION_EXPIRED",
  SESSION_REVOKED: "UI_CONTROL_SESSION_REVOKED",
  PERMISSION_DENIED: "UI_CONTROL_PERMISSION_DENIED",
  PROTOCOL_MISMATCH: "UI_CONTROL_PROTOCOL_MISMATCH",
  STALE_GENERATION: "UI_CONTROL_STALE_GENERATION",
  STALE_REVISION: "UI_CONTROL_STALE_REVISION",
  SNAPSHOT_DRIFT: "UI_CONTROL_SNAPSHOT_DRIFT",
  PENDING_LIMIT: "UI_CONTROL_PENDING_LIMIT",
  OPERATION_CONFLICT: "UI_CONTROL_OPERATION_CONFLICT",
  BACKEND_REJECTED: "UI_CONTROL_BACKEND_REJECTED",
  ACK_MISMATCH: "UI_CONTROL_ACK_MISMATCH",
  AMBIGUOUS_SUBMISSION: "UI_CONTROL_AMBIGUOUS_SUBMISSION",
  ABORTED: "UI_CONTROL_ABORTED",
  TRANSPORT: "UI_CONTROL_TRANSPORT",
});

function freezeDetails(details) {
  if (details === undefined) return Object.freeze({});
  if (details === null || typeof details !== "object" || Array.isArray(details)) {
    throw new TypeError("error details must be an object");
  }
  return Object.freeze({ ...details });
}

export class UiControlError extends Error {
  constructor(code, message, { retryable = false, details, cause } = {}) {
    if (!Object.values(UI_CONTROL_ERROR_CODES).includes(code)) {
      throw new TypeError(`unknown ui.control error code: ${String(code)}`);
    }
    super(message, cause === undefined ? undefined : { cause });
    this.name = "UiControlError";
    this.code = code;
    this.retryable = Boolean(retryable);
    this.details = freezeDetails(details);
  }

  toJSON() {
    return {
      name: this.name,
      code: this.code,
      message: this.message,
      retryable: this.retryable,
      details: this.details,
    };
  }
}

export function isUiControlError(value, code) {
  return (
    value instanceof UiControlError &&
    (code === undefined || value.code === code)
  );
}

export function uiControlError(code, message, options) {
  return new UiControlError(code, message, options);
}

export function asUiControlError(
  value,
  code = UI_CONTROL_ERROR_CODES.TRANSPORT,
  message = "ui.control transport failure",
  options = {},
) {
  if (value instanceof UiControlError) return value;
  return new UiControlError(code, message, { ...options, cause: value });
}
