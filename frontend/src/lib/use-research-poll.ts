"use client";

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import { useDocumentVisible } from "./use-document-visible";
import type { ResearchReport, ResearchStatus } from "./supabase";

const ACTIVE_STATUSES: ResearchStatus[] = ["pending", "researching"];
const POLL_INTERVAL_MS = 2500;

/**
 * Poll a research report while it is in flight.
 *
 * - Polls every 2500ms while status is pending/researching.
 * - Visibility-gated: stops polling when the tab is backgrounded (P-PRF-06).
 * - On terminal status (ready / failed / partial), calls onTerminal once and
 *   invalidates the chat session so the placeholder message refreshes.
 */
export function useResearchPoll(
  notebookId: string,
  reportId: string | null,
  opts: {
    sessionId?: string | null;
    onTerminal?: (report: ResearchReport) => void;
  } = {},
): {
  data: ResearchReport | null;
  isLoading: boolean;
  error: Error | null;
} {
  const qc = useQueryClient();
  const visible = useDocumentVisible();

  const q = useQuery({
    queryKey: ["research-report", reportId],
    queryFn: () =>
      reportId
        ? api.research.get(notebookId, reportId).then((r) => r.data)
        : Promise.resolve(null),
    enabled: !!reportId,
    refetchInterval: (query) => {
      if (!visible) return false;
      const status = query.state.data?.status as ResearchStatus | undefined;
      if (!status) return POLL_INTERVAL_MS;
      return ACTIVE_STATUSES.includes(status) ? POLL_INTERVAL_MS : false;
    },
    refetchIntervalInBackground: false,
  });

  // Fire onTerminal exactly once when status transitions out of active.
  useEffect(() => {
    if (!q.data) return;
    const status = q.data.status;
    if (ACTIVE_STATUSES.includes(status)) return;
    opts.onTerminal?.(q.data);
    if (opts.sessionId) {
      qc.invalidateQueries({
        queryKey: ["chat-session", notebookId, opts.sessionId],
      });
    }
    // Deliberately keyed on the report's status so we re-run once per
    // transition. onTerminal callbacks should be idempotent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data?.status]);

  return {
    data: (q.data ?? null) as ResearchReport | null,
    isLoading: q.isLoading,
    error: (q.error as Error | null) ?? null,
  };
}
