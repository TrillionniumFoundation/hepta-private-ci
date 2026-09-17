export const UI_CONTROL_ERROR_CODES = Object.freeze({
  BACKEND_UNAVAILABLE: "BACKEND_UNAVAILABLE",
  CAPACITY_EXHAUSTED: "CAPACITY_EXHAUSTED",
  INCOMPATIBLE_PROTOCOL: "INCOMPATIBLE_PROTOCOL",
  INVALID_INPUT: "INVALID_INPUT",
  NOT_CONNECTED: "NOT_CONNECTED",
  PROTOCOL_VIOLATION: "PROTOCOL_VIOLATION",
  RECONCILIATION_REQUIRED: "RECONCILIATION_REQUIRED",
  REQUEST_REJECTED: "REQUEST_REJECTED",
  STALE_SNAPSHOT: "STALE_SNAPSHOT",
  UNAUTHENTICATED: "UNAUTHENTICATED",
});

export class UiControlError extends Error {
  constructor(code, message, { cause = undefined, details = undefined } = {}) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "UiControlError";
    this.code = code;
    if (details !== undefined) {
      this.details = Object.freeze({ ...details });
    }
  }
}

export function uiControlError(code, message, options) {
  return new UiControlError(code, message, options);
}
