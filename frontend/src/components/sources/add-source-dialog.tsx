"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, FileText, Link as LinkIcon, Youtube, Type } from "lucide-react";

import { api, uploadFileToSignedUrl } from "@/lib/api";
import { useConfig, getMaxFileBytes } from "@/lib/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const ACCEPT =
  ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown";

const MIME_FOR_EXT: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  txt: "text/plain",
  md: "text/markdown",
};

function inferMime(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return MIME_FOR_EXT[ext] ?? "application/octet-stream";
}

export function AddSourceDialog({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();
  const { data: cfg } = useConfig();
  const MAX_FILE_BYTES = getMaxFileBytes(cfg);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [yt, setYt] = useState("");
  const [textName, setTextName] = useState("");
  const [textContent, setTextContent] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File) {
    if (file.size > MAX_FILE_BYTES) {
      toast.error("File exceeds 50MB limit");
      return;
    }
    upload.mutate(file);
  }

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["sources", notebookId] });
    qc.invalidateQueries({ queryKey: ["notebook", notebookId] });
  }

  function close() {
    setOpen(false);
    setUrl("");
    setYt("");
    setTextName("");
    setTextContent("");
    setProgress(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  const upload = useMutation({
    mutationFn: async (file: File) => {
      if (file.size > MAX_FILE_BYTES) {
        throw new Error("File exceeds 50MB limit");
      }
      const mime = inferMime(file);
      // 1. Init: backend creates row + signed PUT URL.
      const init = await api.sources.uploadInit(notebookId, {
        filename: file.name,
        mime_type: mime,
        size: file.size,
      });
      // 2. PUT direct to Storage with progress.
      setProgress(0);
      await uploadFileToSignedUrl(
        init.data.signed_url,
        file,
        (loaded, total) => setProgress(Math.round((loaded / total) * 100)),
      );
      // 3. Notify backend → kicks off ingestion.
      await api.sources.uploadComplete(notebookId, init.data.source_id);
      return init.data.source_id;
    },
    onSuccess: () => {
      toast.success("Upload started");
      invalidate();
      close();
    },
    onError: (e) => {
      setProgress(null);
      toast.error((e as Error).message);
    },
  });

  const addUrl = useMutation({
    mutationFn: () => api.sources.addUrl(notebookId, url.trim()),
    onSuccess: () => {
      toast.success("URL queued");
      invalidate();
      close();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const addYt = useMutation({
    mutationFn: () => api.sources.addYoutube(notebookId, yt.trim()),
    onSuccess: () => {
      toast.success("YouTube queued");
      invalidate();
      close();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const addText = useMutation({
    mutationFn: () =>
      api.sources.addText(notebookId, textName.trim(), textContent),
    onSuccess: () => {
      toast.success("Text added");
      invalidate();
      close();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="w-full">
          <Plus className="mr-1 h-4 w-4" /> Add source
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a source</DialogTitle>
          <DialogDescription>
            Files (≤50MB), URLs, YouTube videos, or pasted text.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="file">
          <TabsList className="grid grid-cols-4">
            <TabsTrigger value="file" className="gap-1.5">
              <FileText className="h-3.5 w-3.5" /> File
            </TabsTrigger>
            <TabsTrigger value="url" className="gap-1.5">
              <LinkIcon className="h-3.5 w-3.5" /> URL
            </TabsTrigger>
            <TabsTrigger value="youtube" className="gap-1.5">
              <Youtube className="h-3.5 w-3.5" /> YouTube
            </TabsTrigger>
            <TabsTrigger value="text" className="gap-1.5">
              <Type className="h-3.5 w-3.5" /> Text
            </TabsTrigger>
          </TabsList>
          <TabsContent value="file" className="space-y-3">
            <div
              role="button"
              tabIndex={0}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragOver(false);
                const f = e.dataTransfer.files[0];
                if (f) handleFile(f);
              }}
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileRef.current?.click();
                }
              }}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed p-8 text-sm transition",
                isDragOver
                  ? "border-primary bg-primary/10"
                  : "border-border hover:bg-secondary/50",
              )}
            >
              <FileText className="h-8 w-8 text-muted-foreground" />
              <p className="font-medium">Drop a file here or click to choose</p>
              <p className="text-xs text-muted-foreground">
                PDF, DOCX, TXT, MD — up to 50MB
              </p>
              <input
                ref={fileRef}
                type="file"
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                  e.target.value = "";
                }}
              />
            </div>
            {progress !== null && (
              <div className="space-y-1">
                <div className="h-2 w-full overflow-hidden rounded bg-secondary">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  {progress}% uploaded
                </p>
              </div>
            )}
          </TabsContent>
          <TabsContent value="url" className="space-y-3">
            <Input
              placeholder="https://example.com/article"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <Button
              className="w-full"
              disabled={!url.trim() || addUrl.isPending}
              onClick={() => addUrl.mutate()}
            >
              {addUrl.isPending ? "Adding…" : "Add URL"}
            </Button>
          </TabsContent>
          <TabsContent value="youtube" className="space-y-3">
            <Input
              placeholder="https://www.youtube.com/watch?v=..."
              value={yt}
              onChange={(e) => setYt(e.target.value)}
            />
            <Button
              className="w-full"
              disabled={!yt.trim() || addYt.isPending}
              onClick={() => addYt.mutate()}
            >
              {addYt.isPending ? "Adding…" : "Add YouTube"}
            </Button>
          </TabsContent>
          <TabsContent value="text" className="space-y-3">
            <Input
              placeholder="Title"
              value={textName}
              onChange={(e) => setTextName(e.target.value)}
            />
            <Textarea
              rows={6}
              placeholder="Paste text here…"
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
            />
            <Button
              className="w-full"
              disabled={
                !textName.trim() || !textContent.trim() || addText.isPending
              }
              onClick={() => addText.mutate()}
            >
              {addText.isPending ? "Adding…" : "Add text"}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
