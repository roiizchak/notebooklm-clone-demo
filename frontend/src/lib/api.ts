import {
  createClient,
  type AudioOverview,
  type Citation,
  type ChatMessage,
  type ChatMode,
  type ChatSession,
  type Note,
  type Notebook,
  type ResearchReport,
  type Source,
  type StudyKind,
  type StudyMaterial,
} from "./supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authToken(): Promise<string | null> {
  const sb = createClient();
  const { data } = await sb.auth.getSession();
  return data.session?.access_token ?? null;
}

interface ApiOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  body?: BodyInit | null;
}

async function request<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const token = await authToken();
  const headers = new Headers(opts.headers as HeadersInit | undefined);
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_URL}${path}`, {
    ...opts,
    headers,
    body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.body,
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      message = body?.detail || body?.error?.message || message;
    } catch {
      /* swallow */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ChatResponseEnvelope {
  data: {
    message_id: string;
    session_id: string;
    content: string;
    citations: Citation[];
    suggested_questions: string[];
  };
  usage: {
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    model_used: string;
  };
}

export interface ResearchAckEnvelope {
  data: {
    message_id: string;
    session_id: string;
    research_report_id: string;
    status: "pending" | "researching";
  };
}

export interface UploadInitResult {
  source_id: string;
  storage_path: string;
  signed_url: string;
  token: string;
  expires_in: number;
}

/**
 * PUT a file to a Supabase signed upload URL with progress callback.
 * Uses XHR (not fetch) because fetch lacks upload-progress events.
 */
export function uploadFileToSignedUrl(
  signedUrl: string,
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", signedUrl);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (evt) => {
      if (onProgress && evt.lengthComputable) onProgress(evt.loaded, evt.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Upload failed (${xhr.status}): ${xhr.responseText}`));
    };
    xhr.onerror = () => reject(new Error("Upload network error"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(file);
  });
}

export const api = {
  notebooks: {
    list: () => request<{ data: Notebook[] }>("/api/v1/notebooks"),
    get: (id: string) => request<{ data: Notebook }>(`/api/v1/notebooks/${id}`),
    create: (data: { name: string; emoji?: string; description?: string | null }) =>
      request<{ data: Notebook }>("/api/v1/notebooks", { method: "POST", json: data }),
    update: (id: string, data: Partial<Pick<Notebook, "name" | "emoji" | "description">>) =>
      request<{ data: Notebook }>(`/api/v1/notebooks/${id}`, { method: "PATCH", json: data }),
    remove: (id: string) =>
      request<void>(`/api/v1/notebooks/${id}`, { method: "DELETE" }),
  },
  sources: {
    list: (notebookId: string) =>
      request<{ data: Source[] }>(`/api/v1/notebooks/${notebookId}/sources`),
    uploadInit: (
      notebookId: string,
      payload: { filename: string; mime_type: string; size: number },
    ) =>
      request<{ data: UploadInitResult }>(
        `/api/v1/notebooks/${notebookId}/sources/upload-init`,
        { method: "POST", json: payload },
      ),
    uploadComplete: (notebookId: string, sourceId: string) =>
      request<{ data: { id: string; status: string } }>(
        `/api/v1/notebooks/${notebookId}/sources/upload-complete`,
        { method: "POST", json: { source_id: sourceId } },
      ),
    addUrl: (notebookId: string, url: string) =>
      request<{ data: { id: string; status: string } }>(
        `/api/v1/notebooks/${notebookId}/sources/url`,
        { method: "POST", json: { url } },
      ),
    addYoutube: (notebookId: string, url: string) =>
      request<{ data: { id: string; status: string } }>(
        `/api/v1/notebooks/${notebookId}/sources/youtube`,
        { method: "POST", json: { url } },
      ),
    addText: (notebookId: string, name: string, content: string) =>
      request<{ data: { id: string; status: string } }>(
        `/api/v1/notebooks/${notebookId}/sources/text`,
        { method: "POST", json: { name, content } },
      ),
    remove: (notebookId: string, sourceId: string) =>
      request<void>(`/api/v1/notebooks/${notebookId}/sources/${sourceId}`, {
        method: "DELETE",
      }),
  },
  chat: {
    send: (
      notebookId: string,
      payload: {
        message: string;
        session_id?: string | null;
        source_ids?: string[] | null;
        model?: string | null;
        mode?: ChatMode;
      },
    ) =>
      request<ChatResponseEnvelope | ResearchAckEnvelope>(
        `/api/v1/notebooks/${notebookId}/chat`,
        { method: "POST", json: payload },
      ),
    listSessions: (notebookId: string) =>
      request<{ data: ChatSession[] }>(
        `/api/v1/notebooks/${notebookId}/chat/sessions`,
      ),
    getSession: (notebookId: string, sessionId: string) =>
      request<{ data: { session: ChatSession; messages: ChatMessage[] } }>(
        `/api/v1/notebooks/${notebookId}/chat/sessions/${sessionId}`,
      ),
    deleteSession: (notebookId: string, sessionId: string) =>
      request<void>(
        `/api/v1/notebooks/${notebookId}/chat/sessions/${sessionId}`,
        { method: "DELETE" },
      ),
  },
  studies: {
    list: (notebookId: string) =>
      request<{ data: StudyMaterial[] }>(`/api/v1/notebooks/${notebookId}/studies`),
    get: (notebookId: string, kind: StudyKind) =>
      request<{ data: StudyMaterial }>(
        `/api/v1/notebooks/${notebookId}/studies/${kind}`,
      ),
    generate: (notebookId: string, kind: StudyKind) =>
      request<{ data: StudyMaterial }>(
        `/api/v1/notebooks/${notebookId}/studies/${kind}/generate`,
        { method: "POST", json: {} },
      ),
    remove: (notebookId: string, kind: StudyKind) =>
      request<void>(`/api/v1/notebooks/${notebookId}/studies/${kind}`, {
        method: "DELETE",
      }),
  },
  notes: {
    list: (notebookId: string) =>
      request<{ data: Note[] }>(`/api/v1/notebooks/${notebookId}/notes`),
    get: (notebookId: string, noteId: string) =>
      request<{ data: Note }>(`/api/v1/notebooks/${notebookId}/notes/${noteId}`),
    create: (
      notebookId: string,
      payload: {
        type: "written" | "saved_response";
        title?: string | null;
        content: string;
        tags?: string[];
        is_pinned?: boolean;
        original_message_id?: string | null;
      },
    ) =>
      request<{ data: Note }>(`/api/v1/notebooks/${notebookId}/notes`, {
        method: "POST",
        json: payload,
      }),
    update: (
      notebookId: string,
      noteId: string,
      payload: Partial<Pick<Note, "title" | "content" | "tags" | "is_pinned">>,
    ) =>
      request<{ data: Note }>(`/api/v1/notebooks/${notebookId}/notes/${noteId}`, {
        method: "PATCH",
        json: payload,
      }),
    remove: (notebookId: string, noteId: string) =>
      request<void>(`/api/v1/notebooks/${notebookId}/notes/${noteId}`, {
        method: "DELETE",
      }),
  },
  research: {
    list: (notebookId: string, opts: { limit?: number; offset?: number } = {}) => {
      const q = new URLSearchParams();
      if (opts.limit != null) q.set("limit", String(opts.limit));
      if (opts.offset != null) q.set("offset", String(opts.offset));
      const qs = q.toString();
      return request<{ data: ResearchReport[] }>(
        `/api/v1/notebooks/${notebookId}/research${qs ? `?${qs}` : ""}`,
      );
    },
    get: (notebookId: string, reportId: string) =>
      request<{ data: ResearchReport }>(
        `/api/v1/notebooks/${notebookId}/research/${reportId}`,
      ),
    remove: (notebookId: string, reportId: string) =>
      request<void>(`/api/v1/notebooks/${notebookId}/research/${reportId}`, {
        method: "DELETE",
      }),
  },
  audio: {
    list: (notebookId: string) =>
      request<{ data: AudioOverview[] }>(`/api/v1/notebooks/${notebookId}/audio`),
    get: (notebookId: string, audioId: string) =>
      request<{ data: AudioOverview }>(
        `/api/v1/notebooks/${notebookId}/audio/${audioId}`,
      ),
    generate: (
      notebookId: string,
      payload: { target_minutes: 5 | 10 | 15; custom_instructions?: string | null },
    ) =>
      request<{ data: { id: string; status: string } }>(
        `/api/v1/notebooks/${notebookId}/audio/generate`,
        { method: "POST", json: payload },
      ),
    getUrl: (notebookId: string, audioId: string) =>
      request<{ data: { signed_url: string; expires_in: number } }>(
        `/api/v1/notebooks/${notebookId}/audio/${audioId}/url`,
      ),
    remove: (notebookId: string, audioId: string) =>
      request<void>(`/api/v1/notebooks/${notebookId}/audio/${audioId}`, {
        method: "DELETE",
      }),
  },
};
