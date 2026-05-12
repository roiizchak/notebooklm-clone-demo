"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { LogOut, Plus } from "lucide-react";

import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export default function Dashboard() {
  const router = useRouter();
  const qc = useQueryClient();
  const [authChecked, setAuthChecked] = useState(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("📓");
  const [description, setDescription] = useState("");

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

  const notebooksQ = useQuery({
    queryKey: ["notebooks"],
    queryFn: () => api.notebooks.list().then((r) => r.data),
    enabled: authChecked,
  });

  const create = useMutation({
    mutationFn: () =>
      api.notebooks.create({
        name: name.trim(),
        emoji,
        description: description.trim() || null,
      }),
    onSuccess: (r) => {
      toast.success("Notebook created");
      setOpen(false);
      setName("");
      setDescription("");
      qc.invalidateQueries({ queryKey: ["notebooks"] });
      router.push(`/notebooks/${r.data.id}`);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  async function logout() {
    await createClient().auth.signOut();
    router.replace("/auth/login");
  }

  if (!authChecked) return null;

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col px-6 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Notebooks</h1>
          <p className="text-sm text-muted-foreground">
            Your research workspaces.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                New notebook
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create notebook</DialogTitle>
                <DialogDescription>
                  Give it a name. You can add sources after creating it.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <div className="grid grid-cols-[80px_1fr] gap-3">
                  <div className="space-y-2">
                    <label className="text-xs">Emoji</label>
                    <Input
                      value={emoji}
                      onChange={(e) => setEmoji(e.target.value.slice(0, 4))}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs">Name</label>
                    <Input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Q4 Strategy Research"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs">Description (optional)</label>
                  <Textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  disabled={!name.trim() || create.isPending}
                  onClick={() => create.mutate()}
                >
                  {create.isPending ? "Creating…" : "Create"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out" title="Sign out">
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {notebooksQ.isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : notebooksQ.error ? (
        <p className="text-destructive-foreground">
          Failed to load: {(notebooksQ.error as Error).message}
        </p>
      ) : (notebooksQ.data ?? []).length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <h2 className="text-lg font-semibold">No notebooks yet</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            Create a notebook to upload sources, ask questions with citations, and generate study materials and audio overviews.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(notebooksQ.data ?? []).map((nb) => (
            <Link
              key={nb.id}
              href={`/notebooks/${nb.id}`}
              className="block rounded-lg border border-border bg-card p-5 transition-colors hover:border-primary/40"
            >
              <div className="mb-2 text-2xl">{nb.emoji}</div>
              <div className="mb-1 font-semibold">{nb.name}</div>
              <div className="text-xs text-muted-foreground">
                {nb.source_count} source{nb.source_count === 1 ? "" : "s"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
