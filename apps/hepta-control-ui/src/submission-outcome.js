import { UI_CONTROL_ERROR_CODES as C } from "./errors.js";

const rejections = new Set([C.BACKEND_REJECTED, C.OPERATION_CONFLICT, C.STALE_REVISION,
  C.PERMISSION_DENIED, C.SESSION_EXPIRED, C.SESSION_REVOKED, C.PROTOCOL_MISMATCH]);

// Share one classification between in-memory retirement and durable cleanup.
// Everything else, including a malformed ACK, remains indeterminate.
export function definitelyNotAccepted(error) {
  return error?.details?.requestDispatched === false || rejections.has(error?.code);
}
