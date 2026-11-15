import type { ReactNode } from "react";

type Props = {
  title: string;
  updated: string;
  children: ReactNode;
};

export function LegalPage({ title, updated, children }: Props) {
  return (
    <main className="legal-page">
      <p>
        <a href="/">← Interview Bot</a>
      </p>
      <h1>{title}</h1>
      <p className="hint">Last updated {updated}</p>
      {children}
    </main>
  );
}
