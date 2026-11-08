/** Autofocus a text field only with a mouse: on a touch screen it raises the keyboard over the content. */
export const autoFocusField = typeof matchMedia === "function" && matchMedia("(pointer: fine)").matches;
