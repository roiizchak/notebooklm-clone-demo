"use client";

import { useState } from "react";
import { ExternalLink, Globe } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { dispatchHighlight } from "@/lib/source-jump";
import type { Citation } from "@/lib/supabase";

export function CitationPopover({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  const meta = citation.metadata as Record<string, unknown>;
  const isWeb = meta?.type === "web";
  const webUrl = typeof meta?.url === "string" ? (meta.url as string) : null;
  const webDomain = typeof meta?.domain === "string" ? (meta.domain as string) : null;
  const loc = isWeb
    ? webDomain
    : typeof meta?.page === "number"
      ? `p. ${meta.page}`
      : typeof meta?.start === "number"
        ? `${Math.round(meta.start as number)}s`
        : typeof meta?.paragraph === "number"
          ? `¶${meta.paragraph}`
          : null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className="mx-0.5 rounded bg-primary/30 px-1 text-xs font-medium text-primary hover:bg-primary/50"
          aria-label={`Citation ${citation.number}`}
          onMouseEnter={() => setOpen(true)}
          onFocus={() => setOpen(true)}
        >
          [{citation.number}]
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-96 text-sm"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1 truncate font-medium" title={citation.source_name}>
            {isWeb && <Globe className="h-3 w-3 shrink-0 text-muted-foreground" />}
            <span className="truncate">{citation.source_name}</span>
          </span>
          {loc && (
            <span className="shrink-0 text-xs text-muted-foreground">{loc}</span>
          )}
        </div>
        {citation.text_excerpt && (
          <p className="whitespace-pre-wrap text-xs text-muted-foreground">
            {citation.text_excerpt}
          </p>
        )}
        <div className="mt-3 flex items-center justify-between">
          {isWeb ? (
            <span className="truncate text-[10px] text-muted-foreground/70" title={webUrl ?? undefined}>
              {webUrl}
            </span>
          ) : (
            <span className="text-[10px] uppercase text-muted-foreground/70">
              similarity {(citation.similarity * 100).toFixed(0)}%
            </span>
          )}
          {isWeb && webUrl ? (
            <Button asChild size="sm" variant="ghost" className="h-7 gap-1 text-xs">
              <a
                href={webUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setOpen(false)}
              >
                <ExternalLink className="h-3 w-3" />
                Open link
              </a>
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 gap-1 text-xs"
              onClick={() => {
                dispatchHighlight(citation.source_id);
                setOpen(false);
              }}
            >
              <ExternalLink className="h-3 w-3" />
              Open source
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
