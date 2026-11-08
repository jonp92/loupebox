import { useEffect, useRef, useState } from "react";
import { api, type StorageMove, type StorageStatus, type StorageTest, type SystemSetting } from "../api";
import { Bar, Placeholder } from "../Skeleton";
import { useToast } from "../toast";
import { Status } from "../ui/Status";

const NAMES: Record<string, string> = { local: "this server's disk", s3: "the S3 bucket" };
const name = (backend: string) => NAMES[backend] ?? backend;

/** Next to the storage settings: check that the connection works, and move images stored earlier. */
export default function SystemStorage({ settings }: { settings: SystemSetting[] | null }) {
  const toast = useToast();
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState("");
  const [moving, setMoving] = useState<{ done: number; total: number } | null>(null);
  const [moveProblem, setMoveProblem] = useState("");
  const latest = useRef(0);

  function load() {
    const n = ++latest.current;
    api<StorageStatus>("/system/storage").then(
      (s) => n === latest.current && setStatus(s),
      (e) => n === latest.current && setError(e.message),
    );
  }
  useEffect(load, [settings]); // saved settings change what "current storage" means

  async function check() {
    setChecking(true);
    setProblem("");
    try {
      const r = await api<StorageTest>("/system/test-storage", { method: "POST" });
      if (r.status === "ok") toast.success(`Connected: a test file was written to ${name(r.backend)}, read back and removed`);
      else setProblem(r.error ?? "The connection failed.");
    } catch (e) {
      setProblem((e as Error).message);
    }
    setChecking(false);
  }

  /** Move a few files at a time until none are left, so the page shows progress and nothing times out. */
  async function move() {
    if (!status) return;
    setMoveProblem("");
    const total = status.to_move;
    let done = 0;
    setMoving({ done, total });
    try {
      for (;;) {
        const r = await api<StorageMove>("/system/storage/move", { method: "POST" });
        done += r.moved + r.missing;
        setMoving({ done, total });
        if (r.failed > 0 || (r.moved === 0 && r.missing === 0)) {
          setMoveProblem(r.error ?? (r.failed ? "Some images could not be moved." : ""));
          break;
        }
        if (r.remaining === 0) {
          toast.success(`${done} ${done === 1 ? "image" : "images"} moved`);
          break;
        }
      }
    } catch (e) {
      setMoveProblem((e as Error).message);
    }
    setMoving(null);
    load();
  }

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!status) {
    return (
      <Placeholder label="Loading storage status…">
        <section className="panel ph"><Bar w="40%" h="1.2rem" /><Bar w="70%" /><Bar w="30%" h="2rem" /></section>
      </Placeholder>
    );
  }
  const others = Object.entries(status.counts).filter(([backend]) => backend !== status.backend);
  return (
    <section className="panel" aria-labelledby="storage-check-title" aria-busy={checking || moving !== null}>
      <h2 id="storage-check-title">Connection and stored images</h2>
      <p>
        <Status tone={status.configured ? "ok" : "muted"}>{status.configured ? "Ready" : "Not set up"}</Status>{" "}
        New images go to {name(status.backend)}.
        {!status.configured && " Fill in the settings above and save, and sites will not accept images until you do."}
      </p>
      <p className="hint muted">Writes a small test file, reads it back and removes it. Save any changes first.</p>
      <div className="row-actions">
        <button type="button" onClick={check} disabled={!status.configured || checking || moving !== null}>
          {checking ? "Testing…" : "Test connection"}
        </button>
      </div>
      {problem && <p className="error" role="alert">{problem}</p>}

      {others.length > 0 && (
        <>
          <h3 className="section-title">Images stored elsewhere</h3>
          <p>
            {others.map(([backend, n]) => `${n} ${n === 1 ? "image is" : "images are"} still on ${name(backend)}`).join(", ")}.
            They keep working where they are. Move them to {name(status.backend)} to keep everything in one place; the old
            copies are removed once each one has been copied.
          </p>
          <div className="row-actions">
            <button type="button" onClick={move} disabled={!status.configured || moving !== null || checking}>
              {moving ? "Moving…" : `Move ${status.to_move} ${status.to_move === 1 ? "image" : "images"}`}
            </button>
          </div>
          {moving && (
            <p role="status" className="muted">
              Moved {moving.done} of {moving.total}. Keep this page open.
            </p>
          )}
          {moveProblem && <p className="error" role="alert">{moveProblem}</p>}
        </>
      )}
    </section>
  );
}
