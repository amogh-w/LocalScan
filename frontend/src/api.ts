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

export type NameSource = "default" | "manual" | "ai";

export interface NameSuggestion {
  name: string;
  date: string;
  sender: string;
  subject: string;
}

export interface Folder {
  id: string;
  parent_id: string | null;
  name: string;
  position: number;
  count: number;
}

export interface Tag {
  id: string;
  name: string;
  color: string; // a Catppuccin accent name
  count?: number;
}

/** Which documents the library shows. */
export type LibraryView = { kind: "all" } | { kind: "unfiled" } | { kind: "folder"; id: string } | { kind: "tag"; id: string } | { kind: "trash" };

export type Confidence = "high" | "medium" | "low";

/** One proposed document: its pages in the proposed order. `positions` are the pages' numbers in the batch. */
export interface SortGroup {
  page_ids: string[];
  positions: number[];
  confidence: Confidence;
  reason: string;
  name: string;
  order_from_markers: boolean;
}

export interface SortProposal {
  groups: SortGroup[];
  unplaced: { page_id: string; position: number; why: string }[];
  message: string | null;
  split: boolean;
}

export interface Doc {
  id: string;
  name: string;
  name_source?: NameSource;
  folder_id: string | null;
  tags: Tag[];
  created: number;
  deleted_at?: number | null;
  pages: Page[];
  status: Status;
  progress: { step: string; done: number; total: number; detail?: string; percent?: number; stage?: number; stages?: number; elapsed?: number } | null;
  error: string | null;
  outputs: Partial<Record<OutputKind, string>>;
}

/** How much of a page has a saved translation: `read` once its text was read, `done` of `total` paragraphs. */
export interface PageTranslation {
  read: boolean;
  done: number;
  total: number;
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
  languages: { code: string; name: string; native: string }[];
  scan_languages: string[];
  translate_to: string;
  images: { max_edge: number; resize_quality: number; page_dpi: number; page_quality: number };
  export: { preset: string; dpi: number; quality: number; effective: [number, number] };
  defaults: { images: Record<string, number>; export: Record<string, number | string> };
  presets: Record<string, { dpi: number; quality: number }>;
  page_dpis: number[];
}

export interface UploadConfig {
  max_edge: number; // 0 = keep every pixel
  resize_quality: number;
}

export interface Health {
  ocr: { ok: boolean; detail: string };
  translator: { ok: boolean; detail: string };
}

export interface ServiceInfo {
  id: string;
  name: string;
  state: "running" | "starting" | "stopped";
  detail: string;
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
  listDocs: (view: LibraryView = { kind: "all" }) => {
    const q = view.kind === "folder" ? `?folder=${view.id}` : view.kind === "unfiled" ? "?folder=none"
      : view.kind === "tag" ? `?tag=${view.id}` : view.kind === "trash" ? "?trash=true" : "";
    return req<Doc[]>("GET", `/api/docs${q}`);
  },
  emptyTrash: () => req<{ deleted: number }>("POST", "/api/docs/trash/empty"),
  moveDoc: (id: string, folder_id: string | null) => req<Doc>("PATCH", d(id), { folder_id }),
  setDocTags: (id: string, tags: string[]) => req<Doc>("PATCH", d(id), { tags }),
  bulk: (ids: string[], action: "move" | "tag" | "untag" | "delete" | "restore" | "purge", extra: { folder_id?: string | null; tag_id?: string } = {}) =>
    req<{ ok: boolean }>("POST", "/api/docs/bulk", { ids, action, ...extra }),
  listFolders: () => req<Folder[]>("GET", "/api/folders"),
  createFolder: (name: string, parent_id: string | null = null) => req<Folder>("POST", "/api/folders", { name, parent_id }),
  renameFolder: (id: string, name: string) => req<Folder>("PATCH", `/api/folders/${id}`, { name }),
  moveFolder: (id: string, parent_id: string | null) => req<Folder>("PATCH", `/api/folders/${id}`, { parent_id }),
  deleteFolder: (id: string) => req<{ ok: boolean }>("DELETE", `/api/folders/${id}`),
  listTags: () => req<{ tags: Tag[]; colors: string[] }>("GET", "/api/tags"),
  createTag: (name: string, color?: string) => req<Tag>("POST", "/api/tags", { name, color }),
  updateTag: (id: string, patch: { name?: string; color?: string }) => req<Tag>("PATCH", `/api/tags/${id}`, patch),
  deleteTag: (id: string) => req<{ ok: boolean }>("DELETE", `/api/tags/${id}`),
  createDoc: (name = "") => req<Doc>("POST", "/api/docs", { name }),
  getDoc: (id: string) => req<Doc>("GET", d(id)),
  renameDoc: (id: string, name: string, name_source: "manual" | "ai" = "manual") =>
    req<Doc>("PATCH", d(id), { name, name_source }),
  sortPages: (id: string, split = true) => req<SortProposal>("POST", `${d(id)}/sort-pages?split=${split}`),
  sortProgress: (id: string) => req<{ stage?: string; done?: number; total?: number }>("GET", `${d(id)}/sort-progress`),
  applySort: (id: string, groups: { page_ids: string[]; name: string; name_source: "ai" | "manual" }[]) =>
    req<{ documents: Doc[] }>("POST", `${d(id)}/apply-sort`, { groups }),
  suggestName: (id: string) => req<NameSuggestion>("POST", `${d(id)}/suggest-name`),
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
  uploadConfig: () => req<UploadConfig>("GET", "/api/upload-config"),
  movePages: (id: string, page_ids: string[], folder_id?: string | null) =>
    req<{ document: Doc; positions: number[]; source: Doc }>("POST", `${d(id)}/move-pages`,
      folder_id === undefined ? { page_ids } : { page_ids, folder_id }),
  returnPages: (id: string, page_ids: string[], from_doc_id: string, positions: number[]) =>
    req<Doc>("POST", `${d(id)}/return-pages`, { page_ids, from_doc_id, positions }),
  removePages: (id: string, page_ids: string[]) => req<Doc>("POST", `${d(id)}/remove-pages`, { page_ids }),
  deletePage: (id: string, pid: string) => req<Doc>("DELETE", `${d(id)}/pages/${pid}`),
  process: (id: string, force = false) => req<Doc>("POST", `${d(id)}/process${force ? "?force=true" : ""}`),
  translatePage: (id: string, pid: string, force = false) =>
    req<Doc>("POST", `${d(id)}/pages/${pid}/translate${force ? "?force=true" : ""}`),
  clearPageTranslation: (id: string, pid: string) => req<Doc>("DELETE", `${d(id)}/pages/${pid}/translation`),
  clearTranslations: (id: string) => req<Doc>("DELETE", `${d(id)}/translations`),
  translationStatus: (id: string) => req<Record<string, PageTranslation>>("GET", `${d(id)}/translation-status`),
  getSettings: () => req<Settings>("GET", "/api/settings"),
  putSettings: (patch: Partial<Pick<Settings, "ollama_model" | "ollama_url" | "paddle_url">> & { ocr_engine?: string; scan_languages?: string[]; translate_to?: string; images?: Record<string, number>; export?: Record<string, number | string> }) =>
    req<Settings>("PUT", "/api/settings", patch),
  health: () => req<Health>("GET", "/api/health"),
  services: () => req<ServiceInfo[]>("GET", "/api/services"),
  startService: (id: string) => req<ServiceInfo>("POST", `/api/services/${id}/start`),
  stopService: (id: string) => req<ServiceInfo>("POST", `/api/services/${id}/stop`),
  serviceLogs: (id: string) => req<{ text: string }>("GET", `/api/services/${id}/logs?lines=200`),
  serverInfo: () => req<{ lan_url: string; dev_url: string | null }>("GET", "/api/server-info"),
};

export const imageUrl = (id: string, pid: string, max = 1600) => `${d(id)}/pages/${pid}/image?max=${max}`;

export const translatedUrl = (id: string, pid: string, v: number | string, max = 1200) =>
  `${d(id)}/pages/${pid}/translated?max=${max}&v=${v}`;

export const previewUrl = (id: string, p: Page, max = 1200) =>
  `${d(id)}/pages/${p.id}/preview?max=${max}&v=${encodeURIComponent(
    JSON.stringify([p.corners, p.rotation, p.filter]),
  )}`;

export const fileUrl = (id: string, kind: OutputKind, inline = false) =>
  `${d(id)}/files/${kind}${inline ? "?inline=true" : ""}`;

/**
 * Get a camera photo ready for upload. With no size limit a JPEG or PNG goes up exactly as it is (the server
 * applies its EXIF orientation), so nothing is lost and nothing is re-encoded. Otherwise (a limit is set, or a
 * format the server may not read) it is drawn upright on a canvas, shrunk to the limit, and encoded as JPEG.
 */
export async function prepareImage(file: File, cfg: UploadConfig = { max_edge: 0, resize_quality: 92 }): Promise<Blob> {
  if (!cfg.max_edge && (file.type === "image/jpeg" || file.type === "image/png")) return file;
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const s = cfg.max_edge ? Math.min(1, cfg.max_edge / Math.max(bmp.width, bmp.height)) : 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bmp.width * s);
  canvas.height = Math.round(bmp.height * s);
  canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  bmp.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode failed"))), "image/jpeg", cfg.resize_quality / 100),
  );
}

/** Folders as an indented, depth-first list (for pickers), children sorted after their parent. */
export function flattenFolders(folders: Folder[]): (Folder & { depth: number })[] {
  const kids = new Map<string | null, Folder[]>();
  for (const f of folders) kids.set(f.parent_id, [...(kids.get(f.parent_id) ?? []), f]);
  const out: (Folder & { depth: number })[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const f of kids.get(parent) ?? []) {
      out.push({ ...f, depth });
      walk(f.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}
