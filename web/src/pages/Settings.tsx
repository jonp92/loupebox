import { useState, type FormEvent } from "react";
import { api, json, type Site } from "../api";

export default function Settings({ site, onChange }: { site: Site; onChange: (s: Site) => void }) {
  const [msg, setMsg] = useState("");
  const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

  async function run(p: Promise<Site>, ok: string) {
    try {
      onChange(await p);
      setMsg(ok);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    run(
      api<Site>(`/sites/${site.id}`, json("PATCH", {
        name: d.get("name"),
        allowed_origins: String(d.get("origins")).split(/[\s,]+/).filter(Boolean),
        daily_limit: Number(d.get("daily_limit")),
        is_active: d.get("is_active") === "on",
      })),
      "Saved",
    );
  }

  function rotate() {
    if (!confirm("Rotate the key? Sites using the old key will stop working until updated.")) return;
    run(api<Site>(`/sites/${site.id}/rotate-key`, { method: "POST" }), "Key rotated");
  }

  const snippet = `fetch("${apiUrl}/v1/feedback", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": "${site.public_key}" },
  body: JSON.stringify({ message, rating, email, page_url: location.href }),
});`;

  return (
    <>
      <section className="card">
        <h2>API key</h2>
        <p>This key is public by design: it identifies the site. Abuse is limited by allowed origins, rate limits and quotas.</p>
        <code className="key">{site.public_key}</code>
        <button className="danger" onClick={rotate}>Rotate key</button>
        <pre>{snippet}</pre>
        <p className="muted">Include a hidden <code>website</code> field in your form and send it along as-is; bots fill it in and are silently dropped.</p>
      </section>
      <form className="card" onSubmit={save} key={site.public_key + site.name}>
        <h2>Settings</h2>
        <label>Name<input name="name" defaultValue={site.name} required /></label>
        <label>Allowed origins<small> (one per line)</small>
          <textarea name="origins" rows={4} defaultValue={site.allowed_origins.join("\n")} />
        </label>
        <label>Daily submission limit<input name="daily_limit" type="number" min={1} defaultValue={site.daily_limit} /></label>
        <label className="inline"><input name="is_active" type="checkbox" defaultChecked={site.is_active} /> Accepting feedback</label>
        <button className="primary">Save changes</button>
        {msg && <p className="muted">{msg}</p>}
      </form>
    </>
  );
}
