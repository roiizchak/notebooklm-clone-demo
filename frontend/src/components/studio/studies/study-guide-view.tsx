"use client";

import type { StudyMaterial } from "@/lib/supabase";

export function StudyGuideView({ item }: { item: StudyMaterial }) {
  const p = item.payload;
  return (
    <div className="space-y-3 text-sm">
      {p.summary && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Summary
          </h4>
          <p>{p.summary}</p>
        </section>
      )}
      {p.objectives && p.objectives.length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Learning objectives
          </h4>
          <ul className="list-disc space-y-1 pl-5">
            {p.objectives.map((o, i) => (
              <li key={i}>{o}</li>
            ))}
          </ul>
        </section>
      )}
      {p.key_concepts && p.key_concepts.length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Key concepts
          </h4>
          <dl className="space-y-2">
            {p.key_concepts.map((c, i) => (
              <div key={i}>
                <dt className="font-medium">{c.name}</dt>
                <dd className="text-muted-foreground">{c.definition}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      {p.review_questions && p.review_questions.length > 0 && (
        <section>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Review questions
          </h4>
          <ol className="list-decimal space-y-1 pl-5">
            {p.review_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
