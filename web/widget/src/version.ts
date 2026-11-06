/** Semantic version of the widget module. v1.x only ever adds optional options, events and exports. */
export const VERSION = "1.0.0";

/**
 * Feature flags, so a page can check what the loaded script supports before relying on it:
 * `if (!capabilities.includes("issue-types")) ...`. New features add a flag here.
 */
export const capabilities: readonly string[] = [
  "floating",
  "inline",
  "issue-types",
  "extra-fields",
  "theme",
  "strings",
  "challenge-pow",
  "events",
  "headless-client",
  "images",
  "auto-init",
];
