import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PrivacyPolicy } from "../legal/PrivacyPolicy";
import { TermsOfService } from "../legal/TermsOfService";

describe("the privacy policy", () => {
  it("says answers are graded but not stored", () => {
    render(<PrivacyPolicy />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Privacy policy");
    expect(screen.getByText(/the text of your answers is sent to be graded and is not stored/i))
      .toBeInTheDocument();
  });

  it("says how to have your data deleted", () => {
    render(<PrivacyPolicy />);

    expect(screen.getByRole("link", { name: "aderevianko@proton.me" })).toHaveAttribute(
      "href",
      "mailto:aderevianko@proton.me",
    );
  });
});

describe("the terms of service", () => {
  it("point to the privacy policy", () => {
    render(<TermsOfService />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Terms of service");
    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/privacy.html",
    );
  });

  it("lead back to the app", () => {
    render(<TermsOfService />);

    expect(screen.getByRole("link", { name: /interview bot/i })).toHaveAttribute("href", "/");
  });
});
