// Types for the vite.config.ts import only. The implementation (construeProxy.mjs)
// is plain Node ESM and is intentionally outside the app's TS program.

export interface ConstrueProxyConfig {
  clientId?: string;
  clientSecret?: string;
  baseUrl: string;
}

/** Connect-style middleware: (req, res, next) => void. */
export function createConstrueProxy(
  cfg: ConstrueProxyConfig,
): (req: any, res: any, next: (err?: unknown) => void) => void;
