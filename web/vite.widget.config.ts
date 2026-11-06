import { defineConfig } from "vite";

/**
 * The embeddable widget: one dependency-free ES module, served at /widget/v1/loupebox.js.
 * Built after the admin app (emptyOutDir is off so it doesn't wipe dist/).
 */
export default defineConfig({
  publicDir: false,
  build: {
    outDir: "dist/widget/v1",
    emptyOutDir: false,
    target: "es2020",
    lib: { entry: "widget/src/index.ts", formats: ["es"], fileName: () => "loupebox.js" },
    rolldownOptions: { output: { codeSplitting: false } },
  },
});
