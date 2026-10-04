import { useEffect, useRef, useState } from "react";

import { TOPIC_LABELS } from "../api/types";
import type { Topic } from "../api/types";

type Props = {
  // Tagged onto the note so the Notes tab says what it was about.
  topic: Topic | null;
  onSave: (text: string) => void;
  onClose: () => void;
};

export function NoteDialog({ topic, onSave, onClose }: Props) {
  const [text, setText] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);

  // Opened through showModal rather than the `open` attribute: that is what
  // brings Escape to close, the focus trap and the backdrop with it.
  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  return (
    <dialog ref={dialog} className="note-dialog" onClose={onClose}>
      <h2>Note to self</h2>
      <p className="hint">Something to come back to and learn properly later.</p>
      {topic !== null && <p className="tag">{TOPIC_LABELS[topic]}</p>}

      <label htmlFor="note">Your note</label>
      <textarea
        id="note"
        rows={4}
        autoFocus
        value={text}
        placeholder="Read up on how an index changes a write, and when it stops being worth it."
        onChange={(event) => setText(event.target.value)}
      />

      <div className="actions">
        <button type="button" onClick={() => onSave(text)} disabled={text.trim() === ""}>
          Save note
        </button>
        <button type="button" className="secondary" onClick={onClose}>
          Cancel
        </button>
      </div>
    </dialog>
  );
}
