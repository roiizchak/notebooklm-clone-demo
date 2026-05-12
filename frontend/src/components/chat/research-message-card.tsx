"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookmarkPlus, Telescope } from "lucide-react";

import { api } from "@/lib/api";
import type { ResearchReport, ResearchStatus } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { ResearchReportBody } from "./research-report-body";

interface Props {
  notebookId: string;
  /** The persisted assistant chat_messages row that owns this report card. */
  messageId: string;
  report: ResearchReport;
}

function statusPill(status: ResearchStatus): { label: string; className: string } {
  switch (status) {
    case "ready":
      return {
        label: "Ready",
        className: "bg-success/15 text-success",
      };
    case "partial":
      return {
        label: "Partial",
        className: "bg-muted text-muted-foreground",
      };
    case "failed":
      return {
        label: "Failed",
        className: "bg-destructive/15 text-destructive",
      };
    default:
      return {
        label: status,
        className: "bg-warning/15 text-warning",
      };
  }
}

export function ResearchMessageCard({ notebookId, messageId, report }: Props) {
  const qc = useQueryClient();
  const pill = statusPill(report.status);
  const content = report.content_md || "";

  const saveToNotes = useMutation({
    mutationFn: () =>
      api.notes.create(notebookId, {
        type: "saved_response",
        title: report.question.slice(0, 120),
        content,
        original_message_id: messageId,
      }),
    onSuccess: () => {
      toast.success("Saved to notes");
      qc.invalidateQueries({ queryKey: ["notes", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (report.status === "failed") {
    return (
      <div className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm">
        <div className="flex items-center gap-2">
          <Telescope className="h-4 w-4 text-destructive" />
          <span className="font-medium">Research failed</span>
        </div>
        <p className="text-muted-foreground">
          {report.error || "Something went wrong while generating this report."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-xs">
        <Telescope className="h-4 w-4 text-primary" />
        <span className="font-semibold uppercase tracking-wide text-muted-foreground">
          Research report
        </span>
        <span className={`ml-auto rounded px-2 py-0.5 ${pill.className}`}>
          {pill.label}
        </span>
      </div>

      <ResearchReportBody notebookId={notebookId} report={report} />

      <div className="flex items-center justify-end gap-2 border-t border-border pt-2 text-xs">
        {report.cost_usd != null && (
          <span className="text-muted-foreground">
            {report.model_stitch} · ${report.cost_usd.toFixed(4)}
          </span>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2"
          disabled={saveToNotes.isPending}
          onClick={() => saveToNotes.mutate()}
        >
          <BookmarkPlus className="mr-1 h-3 w-3" />
          Save
        </Button>
      </div>
    </div>
  );
}
