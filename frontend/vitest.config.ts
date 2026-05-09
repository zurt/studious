import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: [
        "src/api.ts",
        "src/logger.ts",
        "src/router.ts",
        "src/modules/**/*.ts",
      ],
      exclude: [
        "src/modules/breakdown-pane.ts",
        "src/modules/region-list.ts",
        "src/modules/settings-modal.ts",
        "src/modules/shortcuts-help.ts",
        "src/modules/collapsible.ts",
        "src/modules/confirm.ts",
      ],
    },
  },
});
