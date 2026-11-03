import { sha256 } from "./sha256";

export interface PowChallenge {
  mode: "pow";
  algorithm: "sha256";
  token: string;
  bits: number;
}

function leadingZeroBits(hash: Uint8Array): number {
  let zeros = 0;
  for (const byte of hash) {
    if (byte) return zeros + Math.clz32(byte) - 24;
    zeros += 8;
  }
  return zeros;
}

const tick = () => new Promise<void>((resolve) => setTimeout(resolve));

/**
 * Find `n` so that sha256("<token>:<n>") starts with `bits` zero bits and return "<token>:<n>".
 * Yields to the event loop about every 25 ms so the page stays responsive while it works.
 */
export async function solveProofOfWork(token: string, bits: number, signal?: AbortSignal): Promise<string> {
  const enc = new TextEncoder();
  const subtle = globalThis.crypto?.subtle;
  let lastYield = Date.now();
  for (let n = 0; ; n++) {
    const data = enc.encode(`${token}:${n}`);
    const hash = subtle ? new Uint8Array(await subtle.digest("SHA-256", data)) : sha256(data);
    if (leadingZeroBits(hash) >= bits) return `${token}:${n}`;
    if (Date.now() - lastYield > 25) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      await tick();
      lastYield = Date.now();
    }
  }
}
