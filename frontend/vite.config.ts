import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const page = (file: string) => fileURLToPath(new URL(file, import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        app: page("./index.html"),
        privacy: page("./privacy.html"),
        terms: page("./terms.html"),
      },
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: "./src/test-setup.ts",
  },
});
