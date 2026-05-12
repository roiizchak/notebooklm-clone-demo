"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookmarkCheck, NotebookPen, Pin, PinOff, Plus, Trash2 } from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { Note } from "@/lib/supabase";

export function NotesPanel({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const listQ = useQuery({
    queryKey: ["notes", notebookId],
    queryFn: () => api.notes.list(notebookId).then((r) => r.data),
  });

  const create = useMutation({
    mutationFn: () =>
      api.notes.create(notebookId, {
        type: "written",
        title: title.trim() || null,
        content: content.trim(),
      }),
    onSuccess: () => {
      toast.success("Note saved");
      setTitle("");
      setContent("");
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["notes", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const togglePin = useMutation({
    mutationFn: (n: Note) =>
      api.notes.update(notebookId, n.id, { is_pinned: !n.is_pinned }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notes", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.notes.remove(notebookId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notes", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button size="sm" variant="outline" className="w-full">
            <Plus className="mr-1 h-4 w-4" /> New note
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New note</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="Title (optional)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Textarea
              rows={8}
              placeholder="Write your note…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
            <Button
              className="w-full"
              disabled={!content.trim() || create.isPending}
              onClick={() => create.mutate()}
            >
              {create.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {listQ.isLoading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : !listQ.data || listQ.data.length === 0 ? (
        <p className="text-xs text-muted-foreground">No notes yet.</p>
      ) : (
        listQ.data.map((n) => (
          <div
            key={n.id}
            className="space-y-1 rounded-md border border-border p-3 text-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                {n.title && <p className="truncate font-medium">{n.title}</p>}
                <div className="flex flex-wrap items-center gap-1.5">
                  {n.type === "saved_response" ? (
                    <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      <BookmarkCheck className="h-3 w-3" /> Saved from chat
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                      <NotebookPen className="h-3 w-3" /> Written
                    </span>
                  )}
                  <span className="text-[10px] text-muted-foreground">
                    · {new Date(n.updated_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
              <div className="flex gap-0.5">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={() => togglePin.mutate(n)}
                  title={n.is_pinned ? "Unpin" : "Pin"}
                >
                  {n.is_pinned ? (
                    <PinOff className="h-3.5 w-3.5" />
                  ) : (
                    <Pin className="h-3.5 w-3.5" />
                  )}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={() => remove.mutate(n.id)}
                  title="Delete"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            <p className="whitespace-pre-wrap break-words text-muted-foreground">
              {n.content.length > 400 ? n.content.slice(0, 400) + "…" : n.content}
            </p>
          </div>
        ))
      )}
    </div>
  );
}
