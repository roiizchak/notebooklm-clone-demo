"use client";

import { useState } from "react";
import type { StudyMaterial } from "@/lib/supabase";

export function FaqView({ item }: { item: StudyMaterial }) {
  const faqs = item.payload.faqs ?? [];
  const [open, setOpen] = useState<Record<number, boolean>>({});
  if (faqs.length === 0) {
    return <p className="text-xs text-muted-foreground">No FAQs.</p>;
  }
  return (
    <div className="space-y-2">
      {faqs.map((f, i) => {
        const isOpen = !!open[i];
        return (
          <div key={i} className="rounded-md border border-border">
            <button
              type="button"
              onClick={() => setOpen((s) => ({ ...s, [i]: !isOpen }))}
              className="flex w-full items-start justify-between gap-2 p-3 text-left text-sm font-medium"
            >
              <span>{f.q}</span>
              <span className="text-muted-foreground">{isOpen ? "−" : "+"}</span>
            </button>
            {isOpen && (
              <div className="border-t border-border p-3 text-sm text-muted-foreground">
                {f.a}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
