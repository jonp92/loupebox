import { Link } from "react-router-dom";
import type { Site } from "../api";
import { useToast } from "../toast";
import { widgetTag } from "../widgetSnippet";

/** Shown instead of "No feedback found" on a site that has never received any: the next step is installing the widget. */
export default function InstallPrompt({ site }: { site: Site }) {
  const toast = useToast();
  const tag = widgetTag(site);
  return (
    <section className="install-prompt" aria-labelledby="install-title">
      <h2 id="install-title">Install the widget to start collecting feedback</h2>
      <p>Paste this into any page on an allowed origin. Feedback appears here as soon as someone sends it.</p>
      <pre>{tag}</pre>
      <div className="row-actions">
        <button onClick={() => toast.attempt(navigator.clipboard.writeText(tag), "Snippet copied")}>Copy snippet</button>
        <Link to={`/sites/${site.id}/settings`}>All options and allowed origins</Link>
        <a href="https://loupebox.dev/collect/widget/" target="_blank" rel="noreferrer">Widget docs</a>
      </div>
      {site.allowed_origins.length === 0 && (
        <p className="error" role="alert">No allowed origins yet, so every submission would be refused. Add one in Settings.</p>
      )}
    </section>
  );
}
