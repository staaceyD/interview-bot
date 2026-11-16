import type { ReactNode } from "react";

import { App } from "./App";
import { PRIVACY_PATH, TERMS_PATH } from "./legal/paths";
import { PrivacyPolicy } from "./legal/PrivacyPolicy";
import { TermsOfService } from "./legal/TermsOfService";

export function pageFor(pathname: string): ReactNode {
  switch (pathname.replace(/\/+$/, "")) {
    case PRIVACY_PATH:
      return <PrivacyPolicy />;
    case TERMS_PATH:
      return <TermsOfService />;
    default:
      return <App />;
  }
}
