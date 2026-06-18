/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PHENOML_CLIENT_ID?: string;
  readonly VITE_PHENOML_CLIENT_SECRET?: string;
  readonly VITE_PHENOML_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
