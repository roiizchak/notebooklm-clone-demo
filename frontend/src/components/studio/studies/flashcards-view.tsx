"use client";

import { useState } from "react";
import type { StudyMaterial } from "@/lib/supabase";

export function FlashcardsView({ item }: { item: StudyMaterial }) {
  const cards = item.payload.flashcards ?? [];
  const [idx, setIdx] = useState(0);
  const [showBack, setShowBack] = useState(false);

  if (cards.length === 0) {
    return <p className="text-xs text-muted-foreground">No cards.</p>;
  }
  const card = cards[Math.min(idx, cards.length - 1)];

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Card {idx + 1} of {cards.length}
      </p>
      <button
        type="button"
        aria-pressed={showBack}
        aria-expanded={showBack}
        aria-controls={`card-${idx}-back`}
        onClick={() => setShowBack((v) => !v)}
        className="block w-full rounded-md border border-border bg-secondary p-4 text-left text-sm"
      >
        <p className="font-medium">{card.front}</p>
        {showBack && (
          <p
            id={`card-${idx}-back`}
            className="mt-3 border-t border-border pt-3 text-muted-foreground"
          >
            {card.back}
          </p>
        )}
        {!showBack && (
          <p className="mt-3 text-xs text-muted-foreground">Click to reveal</p>
        )}
      </button>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={idx === 0}
          onClick={() => {
            setIdx((i) => Math.max(0, i - 1));
            setShowBack(false);
          }}
          className="flex-1 rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
        >
          Prev
        </button>
        <button
          type="button"
          disabled={idx >= cards.length - 1}
          onClick={() => {
            setIdx((i) => Math.min(cards.length - 1, i + 1));
            setShowBack(false);
          }}
          className="flex-1 rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
