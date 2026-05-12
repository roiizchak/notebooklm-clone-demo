import { createBrowserClient } from "@supabase/ssr";

export type SourceStatus = "pending" | "processing" | "ready" | "failed";
export type SourceType = "pdf" | "docx" | "url" | "youtube" | "text";

export interface Notebook {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  emoji: string;
  settings: Record<string, unknown>;
  source_count: number;
  created_at: string;
  updated_at: string;
}

export interface Source {
  id: string;
  notebook_id: string;
  type: SourceType;
  name: string;
  status: SourceStatus;
  file_path: string | null;
  original_filename: string | null;
  mime_type: string | null;
  file_size_bytes: number | null;
  token_count: number | null;
  metadata: Record<string, unknown>;
  source_guide: {
    summary?: string;
    topics?: string[];
    suggested_questions?: string[];
  } | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  number: number;
  chunk_id: string;
  source_id: string;
  source_name: string;
  text_excerpt: string;
  metadata: Record<string, unknown>;
  similarity: number;
}

export type ChatMode = "chat" | "research";

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  source_ids_used: string[];
  model_used: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  created_at: string;
  mode?: ChatMode;
  research_report_id?: string | null;
}

export interface ChatSession {
  id: string;
  notebook_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}

// ---------- Phase 2 types ----------

export type StudyKind = "flashcards" | "quiz" | "study_guide" | "faq";

export interface Flashcard {
  front: string;
  back: string;
}

export interface QuizQuestion {
  q: string;
  options: string[];
  correct_index: number;
  explanation?: string;
}

export interface StudyGuidePayload {
  objectives?: string[];
  key_concepts?: { name: string; definition: string }[];
  summary?: string;
  review_questions?: string[];
}

export interface FaqItem {
  q: string;
  a: string;
}

export interface StudyMaterial {
  id: string;
  notebook_id: string;
  user_id: string;
  kind: StudyKind;
  payload: {
    flashcards?: Flashcard[];
    questions?: QuizQuestion[];
    faqs?: FaqItem[];
  } & StudyGuidePayload;
  source_ids: string[];
  model_used: string;
  cost_usd: number | null;
  created_at: string;
  updated_at: string;
}

export type NoteType = "written" | "saved_response";

export interface Note {
  id: string;
  notebook_id: string;
  user_id: string;
  type: NoteType;
  title: string | null;
  content: string;
  tags: string[];
  is_pinned: boolean;
  original_message_id: string | null;
  created_at: string;
  updated_at: string;
}

export type AudioStatus = "pending" | "generating" | "ready" | "failed";

// ---------- Phase 3.a: Deep research ----------

export type ResearchStatus =
  | "pending"
  | "researching"
  | "ready"
  | "failed"
  | "partial";

export type ResearchSectionStatus =
  | "pending"
  | "researching"
  | "ready"
  | "failed";

export interface ResearchReportSection {
  title: string;
  sub_query?: string | null;
  content_md?: string | null;
  citations: Citation[];
  status: ResearchSectionStatus;
  error?: string | null;
}

export interface ResearchReport {
  id: string;
  notebook_id: string;
  user_id: string;
  session_id: string | null;
  question: string;
  source_ids: string[];
  status: ResearchStatus;
  plan: Record<string, unknown> | null;
  sections: ResearchReportSection[];
  content_md: string | null;
  citations: Citation[];
  model_plan: string | null;
  model_sections: string | null;
  model_stitch: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface AudioOverview {
  id: string;
  notebook_id: string;
  user_id: string;
  status: AudioStatus;
  target_minutes: number;
  custom_instructions: string | null;
  source_ids: string[];
  script: string | null;
  audio_path: string | null;
  duration_seconds: number | null;
  error: string | null;
  cost_usd: number | null;
  model_script: string | null;
  model_tts: string | null;
  created_at: string;
  updated_at: string;
}
