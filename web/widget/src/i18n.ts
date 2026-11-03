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
};

/** Replace `{name}` placeholders. */
export function format(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}
