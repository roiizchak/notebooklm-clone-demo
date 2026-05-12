"use client";

import { useState } from "react";
import type { StudyMaterial } from "@/lib/supabase";

export function QuizView({ item }: { item: StudyMaterial }) {
  const questions = item.payload.questions ?? [];
  const [picks, setPicks] = useState<Record<number, number>>({});
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  if (questions.length === 0) {
    return <p className="text-xs text-muted-foreground">No questions.</p>;
  }

  return (
    <div className="space-y-3">
      {questions.map((q, qi) => {
        const picked = picks[qi];
        const reveal = revealed[qi];
        return (
          <div key={qi} className="space-y-2 rounded-md border border-border p-3">
            <p id={`q-${qi}-prompt`} className="text-sm font-medium">
              {qi + 1}. {q.q}
            </p>
            <div role="radiogroup" aria-labelledby={`q-${qi}-prompt`} className="space-y-1">
              {q.options.map((opt, oi) => {
                const isPicked = picked === oi;
                const isCorrect = q.correct_index === oi;
                let cls = "border-border bg-background hover:bg-secondary";
                if (reveal) {
                  if (isCorrect) cls = "border-success bg-success/10";
                  else if (isPicked && !isCorrect)
                    cls = "border-destructive bg-destructive/10";
                } else if (isPicked) {
                  cls = "border-primary bg-primary/10";
                }
                return (
                  <button
                    key={oi}
                    type="button"
                    role="radio"
                    aria-checked={isPicked}
                    aria-disabled={reveal}
                    onClick={() => {
                      if (reveal) return;
                      setPicks((p) => ({ ...p, [qi]: oi }));
                    }}
                    className={
                      "block w-full rounded border px-2 py-1 text-left text-xs " +
                      cls
                    }
                  >
                    {opt}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              aria-expanded={!!reveal}
              aria-controls={`q-${qi}-explanation`}
              disabled={picked === undefined || reveal}
              onClick={() => setRevealed((r) => ({ ...r, [qi]: true }))}
              className="text-xs text-primary disabled:opacity-40"
              hidden={reveal}
            >
              Reveal answer
            </button>
            {reveal && (
              <p id={`q-${qi}-explanation`} className="text-xs text-muted-foreground">
                {q.explanation}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
