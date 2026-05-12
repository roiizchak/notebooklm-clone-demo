"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Play, Trash2 } from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { AudioOverview } from "@/lib/supabase";
import { useDocumentVisible } from "@/lib/use-document-visible";

const LENGTHS = [5, 10, 15] as const;
type Length = (typeof LENGTHS)[number];

// Empirically observed wall-clock generation times (transcript + TTS + upload).
// Used to surface an ETA hint before generation and a remaining estimate during.
const ETA_SECONDS: Record<Length, number> = {
  5: 120,    // ~2 min
  10: 180,   // ~3 min
  15: 270,   // ~4.5 min, may exceed Vercel ceiling
};

function formatMmSs(secs: number): string {
  const s = Math.max(0, Math.round(secs));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export function AudioPanel({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();
  const [length, setLength] = useState<Length>(10);
  const [instructions, setInstructions] = useState("");
  const visible = useDocumentVisible();

  const listQ = useQuery({
    queryKey: ["audio", notebookId],
    queryFn: () => api.audio.list(notebookId).then((r) => r.data),
    refetchInterval: (q) => {
      if (!visible) return false;
      const data = q.state.data as AudioOverview[] | undefined;
      const inFlight = data?.some(
        (a) => a.status === "pending" || a.status === "generating",
      );
      return inFlight ? 3000 : false;
    },
  });

  const generate = useMutation({
    mutationFn: () =>
      api.audio.generate(notebookId, {
        target_minutes: length,
        custom_instructions: instructions.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Audio queued");
      setInstructions("");
      qc.invalidateQueries({ queryKey: ["audio", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: (audioId: string) => api.audio.remove(notebookId, audioId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audio", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-md border border-border p-3">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">
          Generate audio overview
        </h3>
        <div className="flex gap-2">
          {LENGTHS.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setLength(m)}
              className={
                "flex-1 rounded border px-2 py-1 text-xs " +
                (length === m
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-background text-foreground hover:bg-secondary")
              }
            >
              {m} min
            </button>
          ))}
        </div>
        <Textarea
          rows={3}
          placeholder="Optional: focus on… (e.g. 'skip the introduction, emphasise the methodology')"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <Button
          className="w-full"
          size="sm"
          disabled={generate.isPending}
          onClick={() => generate.mutate()}
        >
          {generate.isPending ? "Queuing…" : "Generate"}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Typically ~{formatMmSs(ETA_SECONDS[length])} to generate.
          {length === 15 && " 15-min target may approach Vercel timeout — best effort."}
        </p>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">
          Past overviews
        </h3>
        {listQ.isLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : !listQ.data || listQ.data.length === 0 ? (
          <p className="text-xs text-muted-foreground">No overviews yet.</p>
        ) : (
          listQ.data.map((a) => (
            <AudioRow
              key={a.id}
              notebookId={notebookId}
              audio={a}
              onDelete={() => remove.mutate(a.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function AudioRow({
  notebookId,
  audio,
  onDelete,
}: {
  notebookId: string;
  audio: AudioOverview;
  onDelete: () => void;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setSrc(null);
  }, [audio.id, audio.status]);

  // Tick once a second while in flight so the elapsed counter updates live.
  useEffect(() => {
    if (audio.status !== "pending" && audio.status !== "generating") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [audio.status]);

  const inFlight = audio.status === "pending" || audio.status === "generating";
  const elapsedSec = inFlight
    ? Math.max(0, (now - new Date(audio.created_at).getTime()) / 1000)
    : 0;
  const etaSec =
    ETA_SECONDS[audio.target_minutes as Length] ?? ETA_SECONDS[10];
  const remainingSec = Math.max(0, etaSec - elapsedSec);
  const pct = Math.min(99, (elapsedSec / etaSec) * 100);

  async function loadAndPlay() {
    if (audio.status !== "ready") return;
    if (src) return;
    setLoading(true);
    try {
      const res = await api.audio.getUrl(notebookId, audio.id);
      setSrc(res.data.signed_url);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const created = new Date(audio.created_at).toLocaleString();

  return (
    <div className="space-y-2 rounded-md border border-border p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">{audio.target_minutes}-min overview</p>
          <p className="text-xs text-muted-foreground">{created}</p>
        </div>
        <div className="flex items-center gap-1">
          <StatusBadge status={audio.status} />
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={onDelete}
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      {audio.custom_instructions && (
        <p className="text-xs italic text-muted-foreground">
          “{audio.custom_instructions}”
        </p>
      )}
      {inFlight && (
        <div className="space-y-1">
          <div
            role="progressbar"
            aria-label="Audio generation progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct)}
            className="h-1.5 w-full overflow-hidden rounded bg-secondary"
          >
            <div
              className="h-full bg-warning transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            {formatMmSs(elapsedSec)} elapsed · ~{formatMmSs(remainingSec)} remaining
          </p>
        </div>
      )}
      {audio.status === "failed" && audio.error && (
        <p className="text-xs text-destructive-foreground">{audio.error}</p>
      )}
      {audio.status === "ready" && (
        <>
          {!src ? (
            <Button
              size="sm"
              variant="outline"
              className="w-full"
              disabled={loading}
              onClick={loadAndPlay}
            >
              {loading ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-1 h-3.5 w-3.5" />
              )}
              {loading ? "Loading…" : "Play"}
            </Button>
          ) : (
            <audio controls preload="metadata" src={src} className="w-full" />
          )}
        </>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: AudioOverview["status"] }) {
  const cls =
    status === "ready"
      ? "bg-success/15 text-success"
      : status === "failed"
        ? "bg-destructive/15 text-destructive"
        : "bg-warning/15 text-warning";
  return (
    <span className={"rounded px-1.5 py-0.5 text-[10px] uppercase " + cls}>
      {status}
    </span>
  );
}
