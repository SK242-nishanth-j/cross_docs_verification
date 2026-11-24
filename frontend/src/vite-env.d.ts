/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTOFILL_TIMEOUT_MS?: string;
  readonly VITE_TRIGGER_TIMEOUT_MS?: string;
  readonly VITE_DEFAULT_TIMEOUT_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
