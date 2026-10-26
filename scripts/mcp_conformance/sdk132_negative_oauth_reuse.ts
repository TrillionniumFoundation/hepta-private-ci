/**
 * Local negative producer for the pinned MCP SDK 1.32 conformance fixture.
 * Deliberately retain AS1 credentials when the fixture moves to AS2. The real
 * SDK now prevents that error, so this producer sends the faulty OAuth wire
 * itself. It can contact only loopback HTTP endpoints from the test fixture.
 */
import { createHash, randomBytes } from "node:crypto";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { extractWWWAuthenticateParams } from "@modelcontextprotocol/sdk/client/auth.js";

type ClientInformation = { client_id: string; client_secret?: string };

function fixtureUrl(value: string | URL): URL {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
    !url.port ||
    url.username ||
    url.password
  ) {
    throw new Error(
      "Negative OAuth producer requires an explicit loopback HTTP fixture",
    );
  }
  return url;
}

async function fixtureFetch(
  url: string | URL,
  init?: RequestInit,
): Promise<Response> {
  return fetch(fixtureUrl(url), { ...init, redirect: "manual" });
}

export async function runNegativeOAuthReuse(serverUrl: string): Promise<void> {
  const server = fixtureUrl(serverUrl);
  let credentials: ClientInformation | undefined;
  let accessToken: string | undefined;
  const redirectUri = "http://localhost:3000/callback";

  async function authorize(challenge: Response): Promise<void> {
    const { resourceMetadataUrl } = extractWWWAuthenticateParams(challenge);
    if (!resourceMetadataUrl)
      throw new Error("Fixture omitted protected resource metadata URL");
    const prm = await (await fixtureFetch(resourceMetadataUrl)).json();
    const issuer = fixtureUrl(prm.authorization_servers[0]);
    const metadata = await (
      await fixtureFetch(
        new URL("/.well-known/oauth-authorization-server", issuer),
      )
    ).json();
    if (!credentials) {
      const response = await fixtureFetch(metadata.registration_endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_name: "auth-test-reuse-credentials",
          redirect_uris: [redirectUri],
          application_type: "native",
          token_endpoint_auth_method: "client_secret_post",
        }),
      });
      if (!response.ok)
        throw new Error(`Fixture registration failed: ${response.status}`);
      credentials = (await response.json()) as ClientInformation;
    }
    // Intentionally no registration when the issuer changes. The original
    // detector must see this previous issuer's actual client_id at AS2.
    const verifier = randomBytes(32).toString("base64url");
    const authorization = fixtureUrl(metadata.authorization_endpoint);
    authorization.search = new URLSearchParams({
      response_type: "code",
      client_id: credentials.client_id,
      redirect_uri: redirectUri,
      scope: "mcp:basic",
      resource: prm.resource,
      code_challenge: createHash("sha256").update(verifier).digest("base64url"),
      code_challenge_method: "S256",
    }).toString();
    const response = await fixtureFetch(authorization);
    const location = response.headers.get("location");
    if (!location)
      throw new Error("Fixture did not return an authorization callback");
    const callback = new URL(location);
    if (callback.origin !== new URL(redirectUri).origin)
      throw new Error("Unexpected fixture callback");
    const code = callback.searchParams.get("code");
    if (!code) throw new Error("Fixture did not return an authorization code");
    const token = await fixtureFetch(metadata.token_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        code,
        redirect_uri: redirectUri,
        code_verifier: verifier,
        client_id: credentials.client_id,
        ...(credentials.client_secret
          ? { client_secret: credentials.client_secret }
          : {}),
        resource: prm.resource,
      }),
    });
    if (!token.ok)
      throw new Error(`Fixture token request failed: ${token.status}`);
    accessToken = (await token.json()).access_token;
  }

  const oauthFetch = async (
    input: string | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const url = fixtureUrl(input);
    if (url.origin !== server.origin)
      throw new Error("Unexpected resource server in negative fixture");
    const request = () => {
      const headers = new Headers(init?.headers);
      if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
      return fixtureFetch(url, { ...init, headers });
    };
    const response = await request();
    if (response.status !== 401 && response.status !== 403) return response;
    await authorize(response);
    return request();
  };
  const client = new Client(
    { name: "auth-test-reuse-credentials", version: "1.0.0" },
    { capabilities: {} },
  );
  const transport = new StreamableHTTPClientTransport(server, {
    fetch: oauthFetch,
  });
  try {
    await client.connect(transport);
    await client.listTools();
    await client.callTool({ name: "test-tool", arguments: {} });
  } finally {
    await transport.close();
  }
}
