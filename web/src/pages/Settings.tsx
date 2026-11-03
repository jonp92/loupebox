import { useEffect, useState, type FormEvent } from "react";
import { API_PREFIX, API_URL, api, json, type Site, type VerifierInfo } from "../api";
import { SchemaFields } from "../components";
import { useConfirm } from "../confirm";
import { useToast } from "../toast";

export default function Settings({ site, onChange }: { site: Site; onChange: (s: Site) => void }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [verifiers, setVerifiers] = useState<VerifierInfo[]>([]);
  const [mode, setMode] = useState(site.challenge_mode);
  const [config, setConfig] = useState<Record<string, unknown>>(site.challenge_config);
  useEffect(() => {
    api<VerifierInfo[]>(`/sites/${site.id}/challenge-verifiers`).then(setVerifiers).catch(() => {});
  }, [site.id]);

  const run = (p: Promise<Site>, ok: string) => toast.attempt(p.then(onChange), ok);

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
      "Settings saved",
    );
  }

  async function saveChallenge(e: FormEvent) {
    e.preventDefault();
    await toast.attempt(
      api<Site>(`/sites/${site.id}`, json("PATCH", {
        challenge_mode: mode,
        ...(mode !== "off" && { challenge_config: config }),
      })).then((updated) => {
        onChange(updated);
        setMode(updated.challenge_mode);
        setConfig(updated.challenge_config);
      }),
      "Bot protection saved",
    );
  }

  function pickMode(next: string) {
    setMode(next);
    // Each verifier has its own settings; start from this site's saved ones only for the active mode.
    setConfig(next === site.challenge_mode ? site.challenge_config : {});
  }

  async function rotate() {
    if (!(await confirm({ title: "Rotate the key?", message: "Sites using the old key will stop working until updated.", confirmLabel: "Rotate", danger: true }))) return;
    run(api<Site>(`/sites/${site.id}/rotate-key`, { method: "POST" }), "Key rotated");
  }

  const snippet = `fetch("${API_URL}${API_PREFIX}/feedback", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": "${site.public_key}" },
  body: JSON.stringify({ message, rating, email, page_url: location.href }),
});`;

  // The widget is served by the web app itself, so its URL is this page's origin.
  const widgetSnippet = `<script type="module">
  import { createWidget } from "${location.origin}/widget/v1/ganymede.js";

  createWidget({
    url: "${API_URL}${API_PREFIX}",
    key: "${site.public_key}",
  });
</script>`;

  const verifier = verifiers.find((v) => v.key === mode);
  const chalSnippet = `// Fetch a challenge, solve it, and send the proof with the submission.
// crypto.subtle needs HTTPS (or localhost); see docs/CLIENT_INTEGRATION.md for a fallback.
const API = "${API_URL}${API_PREFIX}";
const headers = { "Content-Type": "application/json", "X-API-Key": "${site.public_key}" };

async function solve(token, bits) {
  const enc = new TextEncoder();
  for (let n = 0; ; n++) {
    const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(\`\${token}:\${n}\`)));
    let zeros = 0;
    for (const byte of hash) { if (byte) { zeros += Math.clz32(byte) - 24; break; } zeros += 8; }
    if (zeros >= bits) return \`\${token}:\${n}\`;
  }
}

const c = await (await fetch(API + "/feedback/challenge", { method: "POST", headers })).json();
const challenge = c.mode === "pow" ? await solve(c.token, c.bits) : undefined;
await fetch(API + "/feedback", {
  method: "POST",
  headers,
  body: JSON.stringify({ message, challenge, page_url: location.href }),
});`;

  return (
    <>
      <section className="card">
        <h2>Feedback widget</h2>
        <p>
          Paste this into any page to add a feedback button. Visitors can tag what kind of feedback it is (bug, idea,
          question, praise), and you can change the badges, fields, colors and wording. Options and theming:{" "}
          <code>docs/WIDGET.md</code>.
        </p>
        <pre>{widgetSnippet}</pre>
        <div className="row-actions">
          <button onClick={() => toast.attempt(navigator.clipboard.writeText(widgetSnippet), "Snippet copied")}>Copy snippet</button>
        </div>
        {site.allowed_origins.length === 0 && (
          <p className="error" role="alert">
            No allowed origins yet, so every submission from a page will be refused. Add the page's origin below.
          </p>
        )}
        <p className="muted hint">
          The page must be on one of the site's allowed origins (scheme, host and port, e.g. <code>https://www.example.com</code>).
        </p>
      </section>
      <section className="card">
        <h2>API key</h2>
        <p>This key is public by design: it identifies the site. Abuse is limited by allowed origins, rate limits and quotas.</p>
        <code className="key">{site.public_key}</code>
        <button className="danger" onClick={rotate}>Rotate key</button>
        <pre>{snippet}</pre>
        <p className="muted">Include a hidden <code>website</code> field in your form and send it along as-is; bots fill it in and are silently dropped.</p>
      </section>
      <form className="card" onSubmit={saveChallenge}>
        <h2>Bot protection</h2>
        <p className="muted">
          The API key is public, so anything can claim to be your site. A challenge makes each submission cost the sender a
          little work: invisible to visitors, expensive for floods. Turn it on if you are being abused; your form must then
          solve the challenge (snippet below), or submissions are rejected.
        </p>
        <label>Challenge
          <select value={mode} onChange={(e) => pickMode(e.target.value)}>
            <option value="off">Off</option>
            {verifiers.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}
            {mode !== "off" && !verifier && <option value={mode}>{mode} (unavailable)</option>}
          </select>
        </label>
        {verifier && <SchemaFields key={verifier.key} schema={verifier.config_schema} values={config} onChange={setConfig} />}
        <button className="primary">Save</button>
        {site.challenge_mode === "pow" && <pre>{chalSnippet}</pre>}
      </form>
      <form className="card" onSubmit={save} key={site.public_key + site.name}>
        <h2>Settings</h2>
        <label>Name<input name="name" defaultValue={site.name} required /></label>
        <label>Allowed origins<small> (one per line)</small>
          <textarea name="origins" rows={4} defaultValue={site.allowed_origins.join("\n")} />
        </label>
        <label>Daily submission limit<input name="daily_limit" type="number" min={1} defaultValue={site.daily_limit} /></label>
        <label className="inline"><input name="is_active" type="checkbox" defaultChecked={site.is_active} /> Accepting feedback</label>
        <button className="primary">Save changes</button>
      </form>
    </>
  );
}
