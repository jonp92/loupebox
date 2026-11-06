/** What the site accepts, from `GET /feedback/config`. */
export interface ImageLimits {
  maxCount: number;
  maxBytes: number;
  /** Pixels on the longer side; the server scales anything bigger down. */
  maxEdge: number;
}

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];

/** Scale a picture down in the browser so a large screenshot does not have to travel at full size.
 * Anything that cannot be scaled (no canvas, an unreadable file) is returned as it is. */
async function shrink(file: File, limits: ImageLimits): Promise<File | Blob> {
  if (typeof createImageBitmap !== "function" || typeof document === "undefined") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, limits.maxEdge / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= limits.maxBytes) {
      bitmap.close?.();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    const type = file.type === "image/png" ? "image/png" : "image/jpeg";
    const out = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, 0.85));
    return out && out.size < file.size ? out : file;
  } catch {
    return file;
  }
}

/** The file ready to send, or why it cannot be: a type we do not take, or still too big after scaling. */
export async function prepareImage(file: File, limits: ImageLimits): Promise<Blob | "type" | "size"> {
  if (!IMAGE_TYPES.includes(file.type)) return "type";
  const out = await shrink(file, limits);
  return out.size > limits.maxBytes ? "size" : out;
}
