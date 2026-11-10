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
export type { ClientOptions, FeedbackInput, SiteConfig, SubmitResult } from "./client";
export { solveProofOfWork } from "./challenge";
export { defaultIssueTypes, LoupeboxConfigError } from "./options";
export type {
  ColorName, ExtraField, FieldMode, IssueType, MetadataValue, SubmitPayload, WidgetOptions,
} from "./options";
export type { ImageLimits } from "./images";
export { defaultStrings } from "./i18n";
export type { Strings } from "./i18n";
export { capabilities, VERSION } from "./version";

import { autoInit } from "./auto";

// `<script type="module" src=".../loupebox.js" data-key="pk_...">` starts a widget by itself.
autoInit(import.meta.url);
