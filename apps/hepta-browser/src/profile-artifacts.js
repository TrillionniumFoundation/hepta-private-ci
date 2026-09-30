import { randomBytes } from "node:crypto";
import { isAbsolute, join } from "node:path";

// Conservative UTF-8 pathname limit, leaving headroom below Linux sun_path.
export const MAX_BROWSER_SOCKET_PATH_BYTES = 103;

export function browserProfileArtifactPaths(profileRoot) {
  if (typeof profileRoot !== "string" || !isAbsolute(profileRoot) || profileRoot.includes("\0")) {
    throw new TypeError("profileRoot must be an absolute filesystem path");
  }
  // Identity belongs in the checked ownership manifest and private protocol,
  // not an OS pathname. Use 128 random bits, independent of principal/profile
  // name length, and exclusive creation at the actual allocation boundary.
  const nonce = randomBytes(16).toString("hex");
  const profileDir = join(profileRoot, `p.${nonce}`);
  const socketPath = join(profileDir, ".hepta-egress.sock");
  if (Buffer.byteLength(socketPath, "utf8") > MAX_BROWSER_SOCKET_PATH_BYTES) {
    const error = new TypeError("profileRoot is too long for the private Browser Unix socket");
    error.code = "BROWSER_PROFILE_ROOT_TOO_LONG";
    throw error;
  }
  return Object.freeze({
    profileDir,
    socketPath,
    profileOwnerPath: join(profileRoot, `.hepta-profile-owner.${nonce}.json`),
    verifiedWorkerPath: join(profileRoot, `.hepta-verified-worker.${nonce}`),
  });
}
