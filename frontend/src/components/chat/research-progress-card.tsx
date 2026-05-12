"use client";

import { Telescope } from "lucide-react";

import type { ResearchReport, ResearchStatus } from "@/lib/supabase";

interface Props {
  report: ResearchReport | null;
  fallbackStatus?: ResearchStatus;
}

function stagePercent(report: ResearchReport | null): number {
  if (!report) return 5;
  if (report.status === "pending") return 5;
  if (report.status === "researching") {
    // Estimate: 10% for plan, 80% across sections, 10% for stitch.
    const sections = report.sections || [];
    if (sections.length === 0) return 15;
    const ready = sections.filter((s) => s.status === "ready").length;
    const failed = sections.filter((s) => s.status === "failed").length;
    const total = sections.length;
    return Math.min(95, 15 + Math.round(((ready + failed) / total) * 75));
  }
  if (report.status === "ready" || report.status === "partial") return 100;
  return 100;
}

function stageLabel(report: ResearchReport | null): string {
  if (!report) return "Queuing research…";
  if (report.status === "pending") return "Queued — starting up…";
  if (report.status === "researching") {
    const sections = report.sections || [];
    if (sections.length === 0) return "Planning sections…";
    const ready = sections.filter((s) => s.status === "ready").length;
    const failed = sections.filter((s) => s.status === "failed").length;
    const total = sections.length;
    if (ready + failed < total) {
      return `Researching section ${ready + failed + 1} of ${total}…`;
    }
    return "Stitching report…";
  }
  if (report.status === "failed") return "Research failed";
  return "Done";
}

export function ResearchProgressCard({ report }: Props) {
  const pct = stagePercent(report);
  const label = stageLabel(report);
  const sections = report?.sections || [];

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card/60 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Telescope className="h-4 w-4 text-primary" />
        <span>Deep research</span>
        <span className="ml-auto text-xs text-muted-foreground">{label}</span>
      </div>

      <div
        role="progressbar"
        aria-label="Research progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full bg-primary transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      {sections.length > 0 && (
        <ul className="space-y-1 text-xs">
          {sections.map((s, i) => (
            <li key={`${s.title}-${i}`} className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  s.status === "ready"
                    ? "bg-success"
                    : s.status === "failed"
                      ? "bg-destructive"
                      : s.status === "researching"
                        ? "animate-pulse bg-warning"
                        : "bg-muted-foreground/40"
                }`}
                aria-hidden
              />
              <span className="text-muted-foreground">{s.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
