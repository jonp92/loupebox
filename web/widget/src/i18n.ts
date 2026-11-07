/** Every user-visible string. Override any of them with the `strings` option. */
export interface Strings {
  launcher: string;
  title: string;
  close: string;
  issueTypeLabel: string;
  messageLabel: string;
  messagePlaceholder: string;
  ratingLabel: string;
  nameLabel: string;
  emailLabel: string;
  optional: string;
  submit: string;
  sending: string;
  thanksTitle: string;
  thanks: string;
  sendAnother: string;
  required: string;
  invalidEmail: string;
  chooseType: string;
  errorNetwork: string;
  errorRejected: string;
  errorInvalid: string;
  errorRateLimited: string;
  errorChallenge: string;
  addImage: string;
  imageHint: string;
  imageCount: string;
  imagesLabel: string;
  removeImage: string;
  errorImageType: string;
  errorImageSize: string;
  errorImageCount: string;
  captureButton: string;
  captureFailed: string;
  editorTitle: string;
  editorHelp: string;
  editorHelpKeys: string;
  editorCanvasLabel: string;
  toolLabel: string;
  toolHide: string;
  toolMark: string;
  undo: string;
  clear: string;
  cancel: string;
  useCapture: string;
  cornerSet: string;
  penDown: string;
  shapeAdded: string;
}

export const defaultStrings: Strings = {
  launcher: "Feedback",
  title: "Send feedback",
  close: "Close",
  issueTypeLabel: "What kind of feedback is this?",
  messageLabel: "Your feedback",
  messagePlaceholder: "Tell us what happened or what you would like to see",
  ratingLabel: "How would you rate it?",
  nameLabel: "Name",
  emailLabel: "Email",
  optional: "optional",
  submit: "Send feedback",
  sending: "Sending…",
  thanksTitle: "Thank you!",
  thanks: "Your feedback was sent.",
  sendAnother: "Send more feedback",
  required: "Please fill this in.",
  invalidEmail: "Please enter a valid email address.",
  chooseType: "Please choose a type.",
  errorNetwork: "We couldn't reach the server. Check your connection and try again.",
  errorRejected: "We couldn't send your feedback. Please try again later.",
  errorInvalid: "Some of your answers weren't accepted. Please check them and try again.",
  errorRateLimited: "Too many submissions. Please try again in {seconds} seconds.",
  errorChallenge: "This form needs a newer version of the feedback widget. Please reload the page.",
  addImage: "Add image",
  imageHint: "You can also paste or drop an image.",
  imageCount: "{count} of {max} images",
  imagesLabel: "Attached images",
  removeImage: "Remove image {n}",
  errorImageType: "Only PNG, JPEG and WebP images can be attached.",
  errorImageSize: "That image is too large. The limit is {mb} MB.",
  errorImageCount: "You can attach up to {max} images.",
  captureButton: "Capture this page",
  captureFailed: "We couldn't capture the screen. You can still add an image.",
  editorTitle: "Hide anything private",
  editorHelp: "Drag over anything you don't want to share. Hidden areas are blacked out in the picture before it leaves your browser. Use the highlighter to point out the problem.",
  editorHelpKeys: "With the keyboard: arrow keys move the cursor (Shift for bigger steps), Enter starts and finishes a shape, Escape cancels it.",
  editorCanvasLabel: "The captured page. Draw on it to hide or highlight.",
  toolLabel: "Tool",
  toolHide: "Hide",
  toolMark: "Highlight",
  undo: "Undo",
  clear: "Clear",
  cancel: "Cancel",
  useCapture: "Use screenshot",
  cornerSet: "Corner set. Move to the opposite corner, then press Enter.",
  penDown: "Highlighting. Move with the arrow keys, then press Enter to stop.",
  shapeAdded: "Added.",
};

/** Replace `{name}` placeholders. */
export function format(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}
