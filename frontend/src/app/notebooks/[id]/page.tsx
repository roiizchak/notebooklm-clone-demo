"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Library, PanelLeft } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { SourceList } from "@/components/sources/source-list";
import { AddSourceDialog } from "@/components/sources/add-source-dialog";
import { ChatPanel } from "@/components/chat/chat-panel";
import { StudioPanel } from "@/components/studio/studio-panel";
import { formatRelativeTime } from "@/lib/utils";

export default function NotebookPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.replace("/auth/login");
        return;
      }
      setAuthChecked(true);
    });
  }, [router]);

  const notebookQ = useQuery({
    queryKey: ["notebook", id],
    queryFn: () => api.notebooks.get(id).then((r) => r.data),
    enabled: !!id && authChecked,
  });

  const qc = useQueryClient();
  const [emojiDraft, setEmojiDraft] = useState("");
  const [emojiOpen, setEmojiOpen] = useState(false);

  const updateEmoji = useMutation({
    mutationFn: (emoji: string) => api.notebooks.update(id, { emoji }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notebook", id] });
      qc.invalidateQueries({ queryKey: ["notebooks"] });
      setEmojiOpen(false);
      toast.success("Emoji updated");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (!authChecked) return null;

  if (notebookQ.isLoading)
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading…</p>
      </main>
    );

  if (notebookQ.error)
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4">
        <p className="text-destructive-foreground">
          {(notebookQ.error as Error).message}
        </p>
        <Link href="/" className="text-primary underline">
          Back to dashboard
        </Link>
      </main>
    );

  const nb = notebookQ.data;
  if (!nb) return null;

  return (
    <main className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <Popover
            open={emojiOpen}
            onOpenChange={(o) => {
              setEmojiOpen(o);
              if (o) setEmojiDraft(nb.emoji);
            }}
          >
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label="Edit emoji"
                title="Click to change emoji"
                className="text-3xl leading-none transition hover:scale-110"
              >
                {nb.emoji}
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-56 space-y-2">
              <p className="text-xs font-medium">Choose an emoji</p>
              <Input
                autoFocus
                maxLength={4}
                value={emojiDraft}
                onChange={(e) => setEmojiDraft(e.target.value)}
                className="text-2xl"
              />
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setEmojiOpen(false)}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  disabled={!emojiDraft || emojiDraft === nb.emoji || updateEmoji.isPending}
                  onClick={() => updateEmoji.mutate(emojiDraft)}
                >
                  {updateEmoji.isPending ? "Saving…" : "Save"}
                </Button>
              </div>
            </PopoverContent>
          </Popover>
          <div>
            <h1 className="font-semibold leading-none">{nb.name}</h1>
            <p className="text-xs text-muted-foreground">
              {nb.source_count} source{nb.source_count === 1 ? "" : "s"} · Updated{" "}
              {formatRelativeTime(nb.updated_at)}
            </p>
          </div>
        </div>
        {/* Mobile drawer toggles. Hidden >= md. */}
        <div className="flex items-center gap-1 md:hidden">
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open sources">
                <PanelLeft className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="overflow-y-auto">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Sources
              </h2>
              <AddSourceDialog notebookId={id} />
              <SourceList notebookId={id} />
            </SheetContent>
          </Sheet>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open studio">
                <Library className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="overflow-hidden">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Studio
              </h2>
              <div className="flex-1 overflow-hidden">
                <StudioPanel notebookId={id} />
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </header>

      {/* Desktop: 3-col grid. Mobile: chat full width. */}
      <div className="grid flex-1 overflow-hidden md:grid-cols-[280px_1fr_280px] md:divide-x md:divide-border">
        {/* Left: sources — desktop only. */}
        <aside className="hidden flex-col gap-3 overflow-y-auto p-4 md:flex">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Sources
          </h2>
          <AddSourceDialog notebookId={id} />
          <SourceList notebookId={id} />
        </aside>

        {/* Center: chat — always visible. */}
        <section className="flex flex-col overflow-hidden px-4">
          <ChatPanel notebookId={id} />
        </section>

        {/* Right: studio — desktop only. */}
        <aside className="hidden flex-col gap-3 overflow-hidden p-4 md:flex">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Studio
          </h2>
          <div className="flex-1 overflow-hidden">
            <StudioPanel notebookId={id} />
          </div>
        </aside>
      </div>
    </main>
  );
}
