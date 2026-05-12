"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Globe,
  Loader2,
  Trash2,
  Youtube,
  type LucideIcon,
} from "lucide-react";

import { api } from "@/lib/api";
import { type Source, type SourceType } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useHighlightListener } from "@/lib/source-jump";
import { useDocumentVisible } from "@/lib/use-document-visible";
import { cn } from "@/lib/utils";

const TYPE_ICON: Record<SourceType, LucideIcon> = {
  pdf: FileText,
  docx: FileText,
  text: FileText,
  url: Globe,
  youtube: Youtube,
};

export function SourceList({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const visible = useDocumentVisible();
  useHighlightListener((id) => {
    setHighlightedId(id);
    document
      .getElementById(`source-${id}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => setHighlightedId(null), 1500);
  });
  // Phase 1: poll instead of subscribing to Realtime. Polling runs every 3s
  // when at least one source is mid-ingest, otherwise pauses. Also pauses
  // when the tab is hidden to avoid stacking polls across background tabs.
  const sourcesQ = useQuery({
    queryKey: ["sources", notebookId],
    queryFn: () =>
      api.sources.list(notebookId).then((r) => r.data),
    refetchInterval: (q) => {
      if (!visible) return false;
      const data = q.state.data as Source[] | undefined;
      return data?.some((s) => s.status === "processing" || s.status === "pending")
        ? 3000
        : false;
    },
  });

  const remove = useMutation({
    mutationFn: (sourceId: string) =>
      api.sources.remove(notebookId, sourceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sources", notebookId] });
      qc.invalidateQueries({ queryKey: ["notebook", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (sourcesQ.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const sources = sourcesQ.data ?? [];
  if (sources.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
        No sources yet. Click <span className="font-medium">+ Add</span> above.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {sources.map((s) => {
        const Icon = TYPE_ICON[s.type] ?? FileText;
        return (
          <li
            key={s.id}
            id={`source-${s.id}`}
            className={cn(
              "group flex items-start gap-2 rounded-md border border-border bg-card/40 p-2 transition-colors hover:border-primary/30",
              highlightedId === s.id && "ring-2 ring-primary",
            )}
          >
            <Icon className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm" title={s.name}>
                {s.name}
              </div>
              <StatusBadge status={s.status} error={s.error_message} />
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="opacity-0 group-hover:opacity-100"
              onClick={() => remove.mutate(s.id)}
              disabled={remove.isPending}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </li>
        );
      })}
    </ul>
  );
}

function StatusBadge({
  status,
  error,
}: {
  status: Source["status"];
  error: string | null;
}) {
  switch (status) {
    case "ready":
      return (
        <Badge variant="success" className="mt-1 gap-1">
          <CheckCircle2 className="h-3 w-3" /> ready
        </Badge>
      );
    case "processing":
    case "pending":
      return (
        <Badge variant="warning" className="mt-1 gap-1">
          <Loader2 className="h-3 w-3 animate-spin" /> {status}
        </Badge>
      );
    case "failed":
      return (
        <span title={error ?? undefined}>
          <Badge variant="destructive" className="mt-1 gap-1">
            <AlertCircle className="h-3 w-3" /> failed
          </Badge>
        </span>
      );
    default:
      return null;
  }
}
