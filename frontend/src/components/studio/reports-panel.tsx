"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Telescope, Trash2 } from "lucide-react";

import { api } from "@/lib/api";
import type { ResearchReport, ResearchStatus } from "@/lib/supabase";
import { useDocumentVisible } from "@/lib/use-document-visible";
import { Button } from "@/components/ui/button";
import { ResearchReportBody } from "@/components/chat/research-report-body";

function statusPill(status: ResearchStatus): { label: string; className: string } {
  switch (status) {
    case "ready":
      return { label: "Ready", className: "bg-success/15 text-success" };
    case "partial":
      return { label: "Partial", className: "bg-muted text-muted-foreground" };
    case "failed":
      return { label: "Failed", className: "bg-destructive/15 text-destructive" };
    default:
      return { label: status, className: "bg-warning/15 text-warning" };
  }
}

export function ReportsPanel({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();
  const visible = useDocumentVisible();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const listQ = useQuery({
    queryKey: ["research-reports", notebookId],
    queryFn: () => api.research.list(notebookId, { limit: 50 }).then((r) => r.data),
    refetchInterval: (q) => {
      if (!visible) return false;
      const data = q.state.data as ResearchReport[] | undefined;
      const inFlight = data?.some(
        (r) => r.status === "pending" || r.status === "researching",
      );
      return inFlight ? 3000 : false;
    },
  });

  const detailQ = useQuery({
    queryKey: ["research-report", selectedId],
    queryFn: () =>
      selectedId
        ? api.research.get(notebookId, selectedId).then((r) => r.data)
        : Promise.resolve(null),
    enabled: !!selectedId,
  });

  const remove = useMutation({
    mutationFn: (reportId: string) => api.research.remove(notebookId, reportId),
    onSuccess: (_data, reportId) => {
      toast.success("Report deleted");
      if (selectedId === reportId) setSelectedId(null);
      qc.invalidateQueries({ queryKey: ["research-reports", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const reports = listQ.data || [];

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
        <p className="font-semibold text-foreground">Research reports</p>
        <p className="mt-1">
          Switch chat to <span className="font-medium">Deep</span> mode and ask a
          multi-faceted question to generate a multi-section report. Reports
          take ~60-90s and appear here automatically.
        </p>
      </div>

      {listQ.isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : reports.length === 0 ? (
        <p className="text-xs text-muted-foreground">No reports yet.</p>
      ) : (
        <ul className="space-y-2">
          {reports.map((r) => {
            const pill = statusPill(r.status);
            const isSelected = selectedId === r.id;
            return (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(isSelected ? null : r.id)}
                  aria-expanded={isSelected}
                  className={`w-full rounded-md border p-3 text-left transition-colors ${
                    isSelected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-muted/40"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <Telescope className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm font-medium">
                        {r.question}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                        <span className={`rounded px-1.5 py-0.5 ${pill.className}`}>
                          {pill.label}
                        </span>
                        <span>{new Date(r.created_at).toLocaleDateString()}</span>
                        {r.sections?.length > 0 && (
                          <span>· {r.sections.length} sections</span>
                        )}
                        {r.cost_usd != null && (
                          <span>· ${r.cost_usd.toFixed(4)}</span>
                        )}
                      </div>
                    </div>
                    <Button
                      asChild
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 shrink-0"
                      onClick={(e) => {
                        e.stopPropagation();
                      }}
                    >
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label="Delete report"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (
                            window.confirm(
                              `Delete this research report?\n\n"${r.question.slice(0, 120)}"`,
                            )
                          ) {
                            remove.mutate(r.id);
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.stopPropagation();
                            if (
                              window.confirm(
                                `Delete this research report?\n\n"${r.question.slice(0, 120)}"`,
                              )
                            ) {
                              remove.mutate(r.id);
                            }
                          }
                        }}
                      >
                        <Trash2 className="h-3 w-3" />
                      </span>
                    </Button>
                  </div>
                </button>

                {isSelected && (
                  <div className="mt-2 space-y-3 rounded-md border border-border bg-card p-3">
                    {detailQ.isLoading || !detailQ.data ? (
                      <p className="text-xs text-muted-foreground">
                        Loading report…
                      </p>
                    ) : detailQ.data.status === "failed" ? (
                      <div className="text-xs text-destructive">
                        Failed: {detailQ.data.error || "unknown error"}
                      </div>
                    ) : detailQ.data.content_md ? (
                      <ResearchReportBody
                        notebookId={notebookId}
                        report={detailQ.data}
                        defaultFootnotesOpen={false}
                      />
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {detailQ.data.status === "researching"
                          ? "Researching… come back in ~60-90s."
                          : "No content yet."}
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
