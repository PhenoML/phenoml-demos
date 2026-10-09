import { defineConfig, loadEnv, type PluginOption } from 'vite'
import react from '@vitejs/plugin-react'
import { createConstrueProxy } from './server/construeProxy.mjs'

// Standalone SPA. A small server-side middleware (server/construeProxy) holds the
// PhenoML credentials and proxies same-origin /api/* calls to Construe through
// the PhenoML TypeScript SDK, so the client secret is read from .env server-side
// and NEVER shipped to the browser.
export default defineConfig(({ mode }) => {
  // Empty prefix loads NON-VITE vars (PHENOML_*) from .env too. These stay
  // server-side — only VITE_-prefixed vars are ever exposed to client code.
  const env = loadEnv(mode, process.cwd(), '')
  const proxy = createConstrueProxy({
    clientId: env.PHENOML_CLIENT_ID,
    clientSecret: env.PHENOML_CLIENT_SECRET,
    baseUrl: env.PHENOML_BASE_URL || 'https://experiment.app.pheno.ml',
  })

  // Mount the proxy in the hook body (pre-phase) so /api/* is intercepted before
  // Vite's SPA index.html fallback. Runs under both `vite dev` and `vite preview`.
  const construeProxyPlugin: PluginOption = {
    name: 'construe-proxy',
    configureServer(server) {
      server.middlewares.use(proxy)
    },
    configurePreviewServer(server) {
      server.middlewares.use(proxy)
    },
  }

  return {
    plugins: [react(), construeProxyPlugin],
    server: { open: true },
  }
})
