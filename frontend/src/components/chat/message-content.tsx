"use client";

import { Fragment } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Citation } from "@/lib/supabase";
import { CitationPopover } from "./citation-popover";

const CITATION_RE = /\[(\d+)\]/g;

function inlineCitations(text: string, citations: Citation[]) {
  if (!citations.length) return text;
  const map = new Map<number, Citation>();
  citations.forEach((c) => map.set(c.number, c));

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = CITATION_RE.exec(text)) !== null) {
    const num = Number(m[1]);
    const c = map.get(num);
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    if (c) {
      parts.push(<CitationPopover key={`c-${key++}`} citation={c} />);
    } else {
      parts.push(m[0]);
    }
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

export function MessageContent({
  content,
  citations,
}: {
  content: string;
  citations: Citation[];
}) {
  return (
    <div className="prose prose-sm prose-invert max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Inject citation popovers into every text node.
          p: ({ children }) => (
            <p>
              {asArray(children).map((child, i) =>
                typeof child === "string" ? (
                  <Fragment key={i}>{inlineCitations(child, citations)}</Fragment>
                ) : (
                  <Fragment key={i}>{child}</Fragment>
                ),
              )}
            </p>
          ),
          li: ({ children }) => (
            <li>
              {asArray(children).map((child, i) =>
                typeof child === "string" ? (
                  <Fragment key={i}>{inlineCitations(child, citations)}</Fragment>
                ) : (
                  <Fragment key={i}>{child}</Fragment>
                ),
              )}
            </li>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function asArray(children: React.ReactNode): React.ReactNode[] {
  return Array.isArray(children) ? children : [children];
}
