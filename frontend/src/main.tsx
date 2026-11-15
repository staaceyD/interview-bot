import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { pageFor } from "./pages";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>{pageFor(window.location.pathname)}</StrictMode>,
);
