/**
 * Negative client for SEP-2352: uses a single provider with no issuer keying,
 * so when PRM authorization_servers changes it presents the previous AS's
 * client_id at the new AS. Expected to trigger
 * sep-2352-no-reuse-on-as-change / sep-2352-reregister-on-as-change FAILURE.
 */
import { runAsCli } from './helpers/cliRunner';
import { runNegativeOAuthReuse } from '../../../../../scripts/mcp_conformance/sdk132_negative_oauth_reuse';

export const runClient = runNegativeOAuthReuse;

runAsCli(
  runClient,
  import.meta.url,
  'auth-test-reuse-credentials <server-url>'
);
