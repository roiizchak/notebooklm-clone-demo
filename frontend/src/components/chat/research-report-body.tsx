"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileText, Globe } from "lucide-react";

import { api } from "@/lib/api";
import type { Citation, ResearchReport } from "@/lib/supabase";
import { dispatchHighlight } from "@/lib/source-jump";
import { MessageContent } from "./message-content";

interface Props {
  notebookId: string;
  report: ResearchReport;
  /** Some hosts (the studio Reports tab) want footnotes collapsed by default. */
  defaultFootnotesOpen?: boolean;
}

interface UsedSource {
  id: string;
  name: string;
  count: number;
  isWeb: boolean;
  url: string | null;
}

/**
 * Renders the body of a research report: sources-pills row, markdown content
 * with inline citation popovers, and a collapsible footnotes list.
 *
 * Used by both the chat-thread card (``ResearchMessageCard``) and the studio
 * Reports tab (``ReportsPanel``) so both views show the same source affordances.
 * Handles two citation flavours via ``citation.metadata.type``:
 *   - ``"web"``  (Phase 3.a knowledge-only mode, google_search grounding)
 *   - undefined  (sourced mode, notebook chunk citations)
 */
export function ResearchReportBody({
  notebookId,
  report,
  defaultFootnotesOpen = true,
}: Props) {
  const [showFootnotes, setShowFootnotes] = useState(defaultFootnotesOpen);

  const citations = (report.citations as Citation[]) || [];
  const content = report.content_md || "";

  // Distinguish "knowledge-only because notebook is empty" from "knowledge-only
  // because retrieval missed AND grounding produced nothing" so the empty
  // state explains itself.
  const sourcesQ = useQuery({
    queryKey: ["sources", notebookId],
    queryFn: () => api.sources.list(notebookId).then((r) => r.data),
  });
  const readyCount = (sourcesQ.data ?? []).filter((s) => s.status === "ready").length;

  // Unique sources used across all citations, first-seen order preserved so
  // numbering stays stable.
  const sourcesUsed = useMemo<UsedSource[]>(() => {
    const seen = new Map<string, UsedSource>();
    for (const c of citations) {
      const meta = (c.metadata ?? {}) as Record<string, unknown>;
      const isWeb = meta?.type === "web";
      const url = isWeb && typeof meta.url === "string" ? (meta.url as string) : null;
      const existing = seen.get(c.source_id);
      if (existing) {
        existing.count += 1;
      } else {
        seen.set(c.source_id, {
          id: c.source_id,
          name: c.source_name,
          count: 1,
          isWeb,
          url,
        });
      }
    }
    return Array.from(seen.values());
  }, [citations]);

  return (
    <>
      {sourcesUsed.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="text-muted-foreground">Sources:</span>
          {sourcesUsed.map((s) =>
            s.isWeb && s.url ? (
              <a
                key={s.id}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary hover:bg-primary/20"
                title={s.url}
              >
                <Globe className="h-2.5 w-2.5" />
                <span className="max-w-[160px] truncate">{s.name}</span>
                {s.count > 1 && (
                  <span className="text-[10px] opacity-70">·{s.count}</span>
                )}
              </a>
            ) : (
              <button
                key={s.id}
                type="button"
                onClick={() => dispatchHighlight(s.id)}
                className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary hover:bg-primary/20"
                title={`Jump to ${s.name}`}
              >
                <FileText className="h-2.5 w-2.5" />
                <span className="max-w-[160px] truncate">{s.name}</span>
                {s.count > 1 && (
                  <span className="text-[10px] opacity-70">·{s.count}</span>
                )}
              </button>
            ),
          )}
        </div>
      ) : readyCount > 0 ? (
        <div className="text-[11px] text-warning">
          No chunks retrieved from your {readyCount} ready source
          {readyCount === 1 ? "" : "s"} and web grounding produced no usable
          hits. The report was written from general knowledge. Try rephrasing
          the question or check that your sources cover the topic.
        </div>
      ) : (
        <div className="text-[11px] text-muted-foreground">
          Knowledge-only report — no sources cited. Try a more search-friendly
          question, or attach sources to your notebook.
        </div>
      )}

      <MessageContent content={content} citations={citations} />

      {citations.length > 0 && (
        <div className="border-t border-border pt-2">
          <button
            type="button"
            onClick={() => setShowFootnotes((v) => !v)}
            aria-expanded={showFootnotes}
            aria-controls={`research-footnotes-${report.id}`}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {showFootnotes ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            Citations ({citations.length})
          </button>
          {showFootnotes && (
            <ol
              id={`research-footnotes-${report.id}`}
              className="mt-2 space-y-1 text-xs text-muted-foreground"
            >
              {citations.map((c) => {
                const meta = (c.metadata ?? {}) as Record<string, unknown>;
                const isWeb = meta?.type === "web";
                const url =
                  isWeb && typeof meta.url === "string"
                    ? (meta.url as string)
                    : null;
                return (
                  <li key={c.chunk_id} className="flex gap-2">
                    <span className="font-mono text-primary">[{c.number}]</span>
                    <span className="min-w-0 flex-1">
                      {url ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-medium underline-offset-2 hover:underline"
                        >
                          {c.source_name}
                        </a>
                      ) : (
                        <span className="font-medium">{c.source_name}</span>
                      )}
                      {c.text_excerpt && (
                        <span className="ml-1 opacity-70">— {c.text_excerpt}</span>
                      )}
                      {url && (
                        <span className="ml-1 break-all text-[10px] text-muted-foreground/70">
                          {url}
                        </span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </>
  );
}
