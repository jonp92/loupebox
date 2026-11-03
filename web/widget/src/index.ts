/**
 * Loupebox feedback widget, v1.
 *
 *   import { createWidget } from "https://your-loupebox/widget/v1/loupebox.js";
 *   createWidget({ url: "https://your-loupebox/v1/api", key: "pk_..." });
 *
 * Compatibility promise for this URL: v1.x only adds optional options, events, exports and capabilities.
 * Breaking changes ship under /widget/v2/.
 */
export { createWidget } from "./ui";
export type { WidgetController, WidgetEvents } from "./ui";
export { createClient } from "./client";
export type { ClientOptions, FeedbackInput, SubmitResult } from "./client";
export { solveProofOfWork } from "./challenge";
export { defaultIssueTypes, LoupeboxConfigError } from "./options";
export type {
  ColorName, ExtraField, FieldMode, IssueType, MetadataValue, SubmitPayload, WidgetOptions,
} from "./options";
export { defaultStrings } from "./i18n";
export type { Strings } from "./i18n";
export { capabilities, VERSION } from "./version";
