import { TOPIC_LABELS } from "../api/types";
import type { Note } from "../notes";

type Props = {
  notes: Note[];
  onDelete: (id: string) => void;
};

export function NotesTab({ notes, onDelete }: Props) {
  if (notes.length === 0) {
    return (
      <section className="card">
        <h2>Notes</h2>
        <p className="hint">
          Nothing here yet. <strong>Note to self</strong> jots down a topic worth coming
          back to, and it lands here.
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>Notes</h2>
      <p className="hint">Topics you wanted to learn more about, newest first.</p>
      <ul className="notes">
        {notes.map((note) => (
          <li key={note.id}>
            {label(note) !== null && <p className="tag">{label(note)}</p>}
            <p>{note.text}</p>
            <button
              type="button"
              className="secondary"
              // Named with the note itself: a column of buttons all called
              // "Delete" tells a screen reader nothing about which is which.
              aria-label={`Delete note: ${note.text}`}
              onClick={() => onDelete(note.id)}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function label(note: Note): string | null {
  const parts = [note.topic === null ? null : TOPIC_LABELS[note.topic], written(note)];
  const shown = parts.filter((part) => part !== null);
  return shown.length === 0 ? null : shown.join(" · ");
}

function written(note: Note): string | null {
  const date = new Date(note.writtenAt);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString();
}
