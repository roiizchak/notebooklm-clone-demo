"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookmarkPlus, Send, Telescope, Zap } from "lucide-react";

import { api } from "@/lib/api";
import type {
  ChatMessage,
  ChatMode,
  Citation,
  ResearchReport,
  ResearchStatus,
} from "@/lib/supabase";
import { useResearchPoll } from "@/lib/use-research-poll";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MessageContent } from "./message-content";
import { ResearchProgressCard } from "./research-progress-card";
import { ResearchMessageCard } from "./research-message-card";

interface DisplayMessage extends Pick<ChatMessage, "role" | "content"> {
  id: string;
  citations: Citation[];
  pending?: boolean;
  mode?: ChatMode;
  research_report_id?: string | null;
}

const MODE_STORAGE_KEY = (notebookId: string) => `nbm.chat-mode.${notebookId}`;

export function ChatPanel({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [optimistic, setOptimistic] = useState<DisplayMessage[]>([]);
  const [mode, setMode] = useState<ChatMode>("chat");
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingClearAfterRef = useRef<number>(0);

  // Mode persistence per-notebook.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(MODE_STORAGE_KEY(notebookId));
    if (saved === "research" || saved === "chat") setMode(saved);
  }, [notebookId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(MODE_STORAGE_KEY(notebookId), mode);
  }, [notebookId, mode]);

  const sessionQ = useQuery({
    queryKey: ["chat-session", notebookId, sessionId],
    queryFn: () =>
      sessionId
        ? api.chat.getSession(notebookId, sessionId).then((r) => r.data)
        : Promise.resolve(null),
    enabled: !!sessionId,
  });

  // Auto-select the most-recent session on mount so prior chat / research
  // history renders on reload. Without this, sessionId stays null until the
  // user posts a new message and prior context is invisible.
  const sessionsListQ = useQuery({
    queryKey: ["chat-sessions", notebookId],
    queryFn: () => api.chat.listSessions(notebookId).then((r) => r.data),
  });
  useEffect(() => {
    if (sessionId) return;
    const list = sessionsListQ.data;
    if (list && list.length > 0) setSessionId(list[0].id);
  }, [sessionsListQ.data, sessionId]);

  const sourcesQ = useQuery({
    queryKey: ["sources", notebookId],
    queryFn: () => api.sources.list(notebookId).then((r) => r.data),
  });
  const readySources = (sourcesQ.data ?? []).filter((s) => s.status === "ready");

  // Combine persisted messages + optimistic messages.
  const messages: DisplayMessage[] = [
    ...(sessionQ.data?.messages ?? []).map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      citations: m.citations as Citation[],
      mode: m.mode,
      research_report_id: m.research_report_id,
    })),
    ...optimistic,
  ];

  // Derive the in-flight report id from the latest research-mode assistant
  // message. This survives reload — when the page is reopened mid-research,
  // the persisted assistant placeholder ('Researching…') still has the FK,
  // and the poll hook latches onto it. Stops once content has been mirrored.
  function isPlaceholderResearch(m: DisplayMessage): boolean {
    return (
      m.role === "assistant" &&
      m.mode === "research" &&
      !!m.research_report_id &&
      (m.content === "Researching…" || m.id.endsWith("-pending"))
    );
  }
  const activeReportMessage = [...messages]
    .reverse()
    .find(isPlaceholderResearch);
  const activeReportId = activeReportMessage?.research_report_id ?? null;

  // Poll the active research report. Drives the inline ProgressCard while
  // the placeholder message is still showing 'Researching…'. Stops once
  // the backend mirrors the final markdown onto chat_messages.
  const researchPoll = useResearchPoll(notebookId, activeReportId, {
    sessionId,
    onTerminal: (rep) => {
      qc.invalidateQueries({ queryKey: ["research-reports", notebookId] });
      if (rep.status === "failed") toast.error(rep.error || "Research failed");
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length]);

  useEffect(() => {
    const updatedAt = sessionQ.dataUpdatedAt;
    if (
      pendingClearAfterRef.current &&
      updatedAt > pendingClearAfterRef.current
    ) {
      setOptimistic([]);
      pendingClearAfterRef.current = 0;
    }
  }, [sessionQ.dataUpdatedAt]);

  const send = useMutation({
    mutationFn: async (message: string) => {
      const tempId = crypto.randomUUID();
      const pendingPlaceholder: DisplayMessage = {
        id: `${tempId}-pending`,
        role: "assistant",
        content: mode === "research" ? "Researching…" : "Thinking…",
        citations: [],
        pending: true,
        mode,
      };
      setOptimistic((prev) => [
        ...prev,
        { id: tempId, role: "user", content: message, citations: [] },
        pendingPlaceholder,
      ]);
      try {
        const res = await api.chat.send(notebookId, {
          message,
          session_id: sessionId ?? undefined,
          mode,
        });
        return { res, tempId };
      } catch (e) {
        setOptimistic((prev) => prev.filter((m) => !m.id.startsWith(tempId)));
        throw e;
      }
    },
    onSuccess: ({ res }) => {
      setSessionId(res.data.session_id);
      pendingClearAfterRef.current = Date.now();
      qc.invalidateQueries({
        queryKey: ["chat-session", notebookId, res.data.session_id],
      });
      qc.invalidateQueries({ queryKey: ["chat-sessions", notebookId] });
      // Research ack: poll attaches automatically via derived activeReportId
      // from the persisted placeholder message once chat-session refetches.
      // The optimistic '-pending' suffix on the placeholder also drives the
      // ProgressCard until the persisted message lands.
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function submit() {
    const v = draft.trim();
    if (!v || send.isPending) return;
    setDraft("");
    send.mutate(v);
  }

  const saveToNotes = useMutation({
    mutationFn: (m: DisplayMessage) =>
      api.notes.create(notebookId, {
        type: "saved_response",
        content: m.content,
        original_message_id: m.id,
      }),
    onSuccess: () => {
      toast.success("Saved to notes");
      qc.invalidateQueries({ queryKey: ["notes", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function renderAssistantMessage(m: DisplayMessage) {
    // Research-mode assistant message: render specialized card.
    if (m.mode === "research" && m.research_report_id) {
      const polled =
        researchPoll.data && researchPoll.data.id === m.research_report_id
          ? researchPoll.data
          : null;

      // In-flight detection: optimistic placeholder OR persisted message still
      // showing the 'Researching…' placeholder content (backend hasn't mirrored
      // final markdown onto the message yet).
      const isInFlight =
        m.id.endsWith("-pending") || m.content === "Researching…";

      if (isInFlight) {
        return (
          <div key={m.id} className="mr-auto flex max-w-[95%] flex-col gap-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-[10px]">
                A
              </span>
              <span>Assistant</span>
            </div>
            <ResearchProgressCard report={polled} />
          </div>
        );
      }

      // Terminal: prefer polled report when present (has plan / model_stitch /
      // cost), else synthesize from the persisted chat_messages row that the
      // backend mirrored content + citations onto.
      const report: ResearchReport = polled ?? {
        id: m.research_report_id,
        notebook_id: notebookId,
        user_id: "",
        session_id: sessionId,
        question: "",
        source_ids: [],
        status: "ready" as ResearchStatus,
        plan: null,
        sections: [],
        content_md: m.content,
        citations: m.citations,
        model_plan: null,
        model_sections: null,
        model_stitch: "gemini-3.1-pro-preview",
        input_tokens: null,
        output_tokens: null,
        cost_usd: null,
        error: null,
        created_at: "",
        updated_at: "",
        completed_at: null,
      };

      return (
        <div key={m.id} className="mr-auto flex max-w-[95%] flex-col gap-1">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-[10px]">
              A
            </span>
            <span>Assistant · Research</span>
          </div>
          <ResearchMessageCard
            notebookId={notebookId}
            messageId={m.id}
            report={report}
          />
        </div>
      );
    }

    // Default chat-mode assistant message (existing layout).
    return (
      <div key={m.id} className="mr-auto flex max-w-[95%] flex-col gap-1">
        <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-[10px]">
            A
          </span>
          <span>Assistant</span>
        </div>
        <div className="rounded-lg bg-muted/40 px-4 py-3 text-sm">
          {m.pending ? (
            <em className="text-muted-foreground">{m.content}</em>
          ) : (
            <MessageContent content={m.content} citations={m.citations} />
          )}
        </div>
        {!m.pending && !m.id.includes("-pending") && (
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-xs text-muted-foreground"
              disabled={saveToNotes.isPending}
              onClick={() => saveToNotes.mutate(m)}
            >
              <BookmarkPlus className="mr-1 h-3 w-3" />
              Save
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto px-1 py-4"
      >
        {messages.length === 0 && (
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-2 pt-6">
            {readySources.length > 0 && (
              <div className="space-y-3 rounded-md border border-border bg-card p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Your sources ({readySources.length})
                </p>
                <ul className="space-y-2">
                  {readySources.map((s) => (
                    <li key={s.id} className="text-sm">
                      <span className="font-medium">{s.name}</span>
                      {s.source_guide?.summary && (
                        <span className="ml-2 text-muted-foreground">
                          — {s.source_guide.summary.split("\n")[0].slice(0, 140)}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="space-y-1 text-center text-sm text-muted-foreground">
              <p className="text-base font-medium text-foreground">
                Ask anything about your sources
              </p>
              <p>
                Citations like <code className="rounded bg-muted px-1">[1]</code> link to source passages.
                Use <strong>Deep</strong> mode for a multi-section research report.
              </p>
            </div>
          </div>
        )}

        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="ml-auto flex max-w-[85%] flex-col items-end gap-1">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                <span>You</span>
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/30 text-[10px] text-primary">
                  Y
                </span>
              </div>
              <div className="rounded-lg bg-primary/15 px-4 py-2 text-sm">
                <p className="whitespace-pre-wrap">{m.content}</p>
              </div>
            </div>
          ) : (
            renderAssistantMessage(m)
          ),
        )}
      </div>

      <div className="border-t border-border bg-background/60 p-3">
        <div className="mb-2 flex items-center gap-1" role="group" aria-label="Chat mode">
          <Button
            type="button"
            size="sm"
            variant={mode === "chat" ? "default" : "ghost"}
            className="h-7 px-2 text-xs"
            aria-pressed={mode === "chat"}
            onClick={() => setMode("chat")}
          >
            <Zap className="mr-1 h-3 w-3" />
            Quick
          </Button>
          <Button
            type="button"
            size="sm"
            variant={mode === "research" ? "default" : "ghost"}
            className="h-7 px-2 text-xs"
            aria-pressed={mode === "research"}
            onClick={() => setMode("research")}
            title="Deep multi-section research (~60-90s)"
          >
            <Telescope className="mr-1 h-3 w-3" />
            Deep
          </Button>
          {mode === "research" && (
            <span className="ml-2 text-[11px] text-muted-foreground">
              {readySources.length === 0
                ? "~60-90s, knowledge-only (no sources attached)"
                : "~60-90s, multi-section report"}
            </span>
          )}
        </div>
        <div className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              mode === "research"
                ? "Ask a deep research question…"
                : "Ask about your sources…"
            }
            rows={2}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <Button onClick={submit} disabled={!draft.trim() || send.isPending}>
            {mode === "research" ? (
              <Telescope className="h-4 w-4" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
