export type Point = [number, number];
export type Filter = "enhanced" | "original" | "grayscale" | "bw";

export interface Page {
  id: string;
  width: number;
  height: number;
  source: "photo" | "pdf";
  corners: Point[];
  detected: Point[];
  rotation: number;
  filter: Filter;
}

export type Status = "draft" | "queued" | "processing" | "done" | "error";
export type OutputKind = "translated" | "scan" | "side_by_side";

export interface Doc {
  id: string;
  name: string;
  created: number;
  pages: Page[];
  status: Status;
  progress: { step: string; done: number; total: number } | null;
  error: string | null;
  outputs: Partial<Record<OutputKind, string>>;
}

export interface Settings {
  translator: string;
  ollama_url: string;
  ollama_model: string;
  ollama_models: string[];
  ollama_error: string | null;
  ocr: string;
  ocr_engines: string[];
  paddle_url: string;
}

export interface Health {
  ocr: { ok: boolean; detail: string };
  translator: { ok: boolean; detail: string };
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return r.json();
}

const d = (id: string) => `/api/docs/${id}`;

export const api = {
  listDocs: () => req<Doc[]>("GET", "/api/docs"),
  createDoc: (name = "") => req<Doc>("POST", "/api/docs", { name }),
  getDoc: (id: string) => req<Doc>("GET", d(id)),
  renameDoc: (id: string, name: string) => req<Doc>("PATCH", d(id), { name }),
  reorder: (id: string, page_order: string[]) => req<Doc>("PATCH", d(id), { page_order }),
  deleteDoc: (id: string) => req<{ ok: boolean }>("DELETE", d(id)),
  uploadPages: (id: string, files: Blob[]) => {
    const fd = new FormData();
    files.forEach((f, i) => fd.append("files", f, `photo-${i}.jpg`));
    return req<Doc>("POST", `${d(id)}/pages`, fd);
  },
  importPdf: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Doc>("POST", `${d(id)}/import-pdf`, fd);
  },
  patchPage: (id: string, pid: string, patch: Partial<Pick<Page, "corners" | "rotation" | "filter">>) =>
    req<Page>("PATCH", `${d(id)}/pages/${pid}`, patch),
  autodetect: (id: string, pid: string) => req<Page>("POST", `${d(id)}/pages/${pid}/autodetect`),
  deletePage: (id: string, pid: string) => req<Doc>("DELETE", `${d(id)}/pages/${pid}`),
  process: (id: string) => req<Doc>("POST", `${d(id)}/process`),
  getSettings: () => req<Settings>("GET", "/api/settings"),
  putSettings: (patch: Partial<Pick<Settings, "ollama_model" | "ollama_url" | "paddle_url">> & { ocr_engine?: string }) =>
    req<Settings>("PUT", "/api/settings", patch),
  health: () => req<Health>("GET", "/api/health"),
  serverInfo: () => req<{ lan_url: string }>("GET", "/api/server-info"),
};

export const imageUrl = (id: string, pid: string, max = 1600) => `${d(id)}/pages/${pid}/image?max=${max}`;

export const previewUrl = (id: string, p: Page, max = 1200) =>
  `${d(id)}/pages/${p.id}/preview?max=${max}&v=${encodeURIComponent(
    JSON.stringify([p.corners, p.rotation, p.filter]),
  )}`;

export const fileUrl = (id: string, kind: OutputKind, inline = false) =>
  `${d(id)}/files/${kind}${inline ? "?inline=true" : ""}`;

/** Downscale a camera photo before upload, applying EXIF orientation. */
export async function prepareImage(file: File, maxEdge = 3000): Promise<Blob> {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const s = Math.min(1, maxEdge / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bmp.width * s);
  canvas.height = Math.round(bmp.height * s);
  canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  bmp.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode failed"))), "image/jpeg", 0.92),
  );
}
