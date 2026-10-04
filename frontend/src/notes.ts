import { TOPICS } from "./api/types";
import type { Topic } from "./api/types";

const KEY = "interview-bot.notes";

export type Note = {
  id: string;
  text: string;
  // The topic of the question that prompted the note, when there was one. A
  // note written outside an interview belongs to no topic in particular.
  topic: Topic | null;
  writtenAt: string;
};

export function writeNote(text: string, topic: Topic | null): Note {
  return {
    id: crypto.randomUUID(),
    text: text.trim(),
    topic,
    writtenAt: new Date().toISOString(),
  };
}

// Anything stored by an older version, or edited by hand, is dropped rather
// than rendered: one bad entry should not take the whole tab down with it.
function isNote(value: unknown): value is Note {
  if (typeof value !== "object" || value === null) return false;
  const note = value as Record<string, unknown>;
  return (
    typeof note.id === "string" &&
    typeof note.text === "string" &&
    typeof note.writtenAt === "string" &&
    (note.topic === null || TOPICS.includes(note.topic as Topic))
  );
}

// Private browsing and blocked site data make these throw rather than no-op,
// and losing a note is never worth breaking the page over.
export function recallNotes(): Note[] {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === null) return [];
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed.filter(isNote) : [];
  } catch {
    return [];
  }
}

export function rememberNotes(notes: Note[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(notes));
  } catch {
    /* the notes still show this session, they just will not come back */
  }
}
