"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { StudyKind, StudyMaterial } from "@/lib/supabase";

import { FlashcardsView } from "./studies/flashcards-view";
import { QuizView } from "./studies/quiz-view";
import { StudyGuideView } from "./studies/study-guide-view";
import { FaqView } from "./studies/faq-view";

const KINDS: { id: StudyKind; label: string }[] = [
  { id: "flashcards", label: "Flashcards" },
  { id: "quiz", label: "Quiz" },
  { id: "study_guide", label: "Guide" },
  { id: "faq", label: "FAQ" },
];

function itemCount(item: StudyMaterial): number {
  switch (item.kind) {
    case "flashcards":
      return item.payload?.flashcards?.length ?? 0;
    case "quiz":
      return item.payload?.questions?.length ?? 0;
    case "faq":
      return item.payload?.faqs?.length ?? 0;
    case "study_guide":
      return 1;
  }
}

export function StudiesPanel({ notebookId }: { notebookId: string }) {
  const qc = useQueryClient();

  const listQ = useQuery({
    queryKey: ["studies", notebookId],
    queryFn: () => api.studies.list(notebookId).then((r) => r.data),
  });

  const byKind = useMemo<Record<StudyKind, StudyMaterial | undefined>>(() => {
    const out: Record<StudyKind, StudyMaterial | undefined> = {
      flashcards: undefined,
      quiz: undefined,
      study_guide: undefined,
      faq: undefined,
    };
    for (const s of listQ.data ?? []) out[s.kind] = s;
    return out;
  }, [listQ.data]);

  const generate = useMutation({
    mutationFn: (kind: StudyKind) => api.studies.generate(notebookId, kind),
    onSuccess: () => {
      toast.success("Generated");
      qc.invalidateQueries({ queryKey: ["studies", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: (kind: StudyKind) => api.studies.remove(notebookId, kind),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["studies", notebookId] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <Tabs defaultValue="flashcards">
      <TabsList className="grid grid-cols-4">
        {KINDS.map((k) => {
          const item = byKind[k.id];
          const count = item ? itemCount(item) : 0;
          return (
            <TabsTrigger key={k.id} value={k.id} className="gap-1.5">
              {k.label}
              {count > 0 && (
                <span className="rounded bg-primary/20 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                  {count}
                </span>
              )}
            </TabsTrigger>
          );
        })}
      </TabsList>

      {KINDS.map((k) => {
        const item = byKind[k.id];
        const pending = generate.isPending && generate.variables === k.id;
        return (
          <TabsContent key={k.id} value={k.id} className="mt-3 space-y-3">
            {!item ? (
              <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                <p className="mb-2">No {k.label.toLowerCase()} yet.</p>
                <Button
                  size="sm"
                  disabled={pending}
                  onClick={() => generate.mutate(k.id)}
                >
                  {pending ? "Generating…" : `Generate ${k.label}`}
                </Button>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-end gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={pending}
                    onClick={() => generate.mutate(k.id)}
                  >
                    {pending ? "Regenerating…" : "Regenerate"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => remove.mutate(k.id)}
                  >
                    Delete
                  </Button>
                </div>
                {k.id === "flashcards" && <FlashcardsView item={item} />}
                {k.id === "quiz" && <QuizView item={item} />}
                {k.id === "study_guide" && <StudyGuideView item={item} />}
                {k.id === "faq" && <FaqView item={item} />}
              </>
            )}
          </TabsContent>
        );
      })}
    </Tabs>
  );
}
