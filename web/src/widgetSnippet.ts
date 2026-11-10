import { API_PREFIX, API_URL, type Site } from "./api";

/**
 * The script tag that starts the widget. The widget is served by the web app itself, so its URL is this page's
 * origin. It looks for the API next to the script, so the API is named only when it is somewhere else.
 */
export function widgetTag(site: Site): string {
  const apiNextToWidget = API_PREFIX === "/v1/api" && `${API_URL}${API_PREFIX}` === `${location.origin}${API_PREFIX}`;
  return `<script type="module" src="${location.origin}/widget/v1/loupebox.js"
  data-key="${site.public_key}"${apiNextToWidget ? "" : `\n  data-url="${API_URL}${API_PREFIX}"`}></script>`;
}
