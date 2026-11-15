import { StrictMode } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";

export function render(page: ReactNode) {
  createRoot(document.getElementById("root")!).render(<StrictMode>{page}</StrictMode>);
}
