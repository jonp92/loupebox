export const AVATAR_SIZE = 256;
const MAX_INPUT_BYTES = 10 * 1024 * 1024;

/** Center-crop to a square and downscale so the upload stays small. */
export async function toAvatarBlob(file: File): Promise<Blob> {
  if (!/^image\/(png|jpeg|webp|gif|bmp)$/.test(file.type)) throw new Error("Choose a PNG, JPEG or WebP image");
  if (file.size > MAX_INPUT_BYTES) throw new Error("Image is too large (10 MB max)");
  const bitmap = await createImageBitmap(file).catch(() => {
    throw new Error("Could not read that image");
  });
  const side = Math.min(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = AVATAR_SIZE;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, AVATAR_SIZE, AVATAR_SIZE);
  ctx.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Could not process that image"))), "image/jpeg", 0.85),
  );
}
