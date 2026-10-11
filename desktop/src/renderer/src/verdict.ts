/**
 * Wording for answer results. The rule: only say "checked" when the math engine actually checked it.
 */
import type { CheckResponse } from "../../shared/apiTypes";

export interface VerdictCopy {
  headline: string;
  tone: "good" | "bad" | "neutral";
  provenance: string;
}

export function describeVerdict(result: CheckResponse): VerdictCopy {
  switch (result.verdict) {
    case "correct":
      return { headline: "Correct", tone: "good", provenance: "Checked by the math engine." };
    case "incorrect":
      return { headline: "Not correct", tone: "bad", provenance: "Checked by the math engine." };
    case "invalid_input":
      return { headline: "Could not read that answer", tone: "neutral", provenance: "No check was made yet." };
    case "unverifiable":
      return {
        headline: "No verdict given",
        tone: "neutral",
        provenance: "This answer could not be checked automatically, so it was not marked right or wrong.",
      };
  }
}

export const DRAFT_NOTICE =
  "Unreviewed AI draft: hidden from students by default. Shown here only because developer mode is on.";
