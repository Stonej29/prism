import { P } from "../theme";
import type { Idea } from "../types";
import { Backdrop } from "./AskOverlay";
import { Spinner } from "./Spinner";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 16 }}>
      <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, textTransform: "uppercase", letterSpacing: 1.4 }}>
        {title}
      </span>
      <div style={{ marginTop: 6, fontFamily: P.sans, fontSize: 13, lineHeight: 1.6, color: P.mid }}>{children}</div>
    </div>
  );
}

function str(s: Record<string, unknown>, k: string): string {
  const v = s[k];
  return typeof v === "string" ? v : "";
}
function list(s: Record<string, unknown>, k: string): string[] {
  const v = s[k];
  return Array.isArray(v) ? v.map(String).filter(Boolean) : [];
}

export function IdeaView({
  topic,
  idea,
  loading,
  onClose,
  onRate,
}: {
  topic: string;
  idea: Idea | null;
  loading: boolean;
  onClose: () => void;
  onRate: (id: string, rating: number) => void;
}) {
  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>/idea</span>
        {topic && <span style={{ fontFamily: P.mono, fontSize: 12, color: P.lo }}>{topic}</span>}
        <span onClick={onClose} style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>
          esc
        </span>
      </div>

      {loading ? (
        <div style={{ marginTop: 16 }}>
          <Spinner label="Synthesizing an idea from your notes…" />
        </div>
      ) : !idea ? null : (
        <>
          <h2 style={{ fontFamily: P.sans, fontSize: 20, fontWeight: 600, color: P.hi, margin: "8px 0 6px" }}>{idea.title}</h2>
          <p style={{ fontFamily: P.sans, fontSize: 14, color: P.mid, margin: 0, lineHeight: 1.6 }}>{idea.summary}</p>

          {idea.llm_status === "generated" && (
            <>
              {str(idea.structured, "problem") && <Section title="Problem">{str(idea.structured, "problem")}</Section>}
              {str(idea.structured, "approach") && <Section title="Approach">{str(idea.structured, "approach")}</Section>}
              {str(idea.structured, "why_it_fits") && <Section title="Why it fits">{str(idea.structured, "why_it_fits")}</Section>}
              {list(idea.structured, "components").length > 0 && (
                <Section title="Components">
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {list(idea.structured, "components").map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </Section>
              )}
              {list(idea.structured, "risks").length > 0 && (
                <Section title="Risks">
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {list(idea.structured, "risks").map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </Section>
              )}
            </>
          )}

          <div style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, textTransform: "uppercase", letterSpacing: 1.4 }}>
              Rate
            </span>
            {[1, 2, 3, 4, 5].map((n) => (
              <span
                key={n}
                onClick={() => onRate(idea.id, n)}
                style={{
                  width: 30,
                  height: 30,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 7,
                  cursor: "pointer",
                  fontFamily: P.mono,
                  fontSize: 13,
                  color: (idea.rating ?? 0) >= n ? P.bg0 : P.mid,
                  background: (idea.rating ?? 0) >= n ? P.accent : P.bg2,
                  border: `1px solid ${P.line}`,
                }}
              >
                {n}
              </span>
            ))}
            {idea.rating != null && <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>rated {idea.rating}/5</span>}
          </div>
        </>
      )}
    </Backdrop>
  );
}
