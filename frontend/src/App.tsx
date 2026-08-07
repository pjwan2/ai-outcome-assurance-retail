import React from "react";
import { api, AuthorityRecord, Claim, Evidence, ReleaseResult, ReviewTask, TraceEvent, CaseSummary } from "./api";

const TABS = ["Case Overview", "Evidence & Claims", "Review Queue", "Trace & Release"] as const;
type Tab = (typeof TABS)[number];

function Badge({ children, tone }: { children: React.ReactNode; tone: "neutral" | "good" | "warn" | "bad" }) {
  const colors: Record<string, string> = {
    neutral: "#e5e7eb",
    good: "#bbf7d0",
    warn: "#fef08a",
    bad: "#fecaca",
  };
  return (
    <span
      style={{
        background: colors[tone],
        borderRadius: 4,
        padding: "2px 8px",
        fontSize: 12,
        fontWeight: 600,
        marginRight: 6,
        display: "inline-block",
      }}
    >
      {children}
    </span>
  );
}

function claimTone(status: string): "good" | "warn" | "bad" {
  if (status === "TRUE") return "good";
  if (status === "UNKNOWN") return "warn";
  return "bad";
}

function decisionTone(decision: string): "good" | "warn" | "bad" {
  if (decision === "ALLOW") return "good";
  if (decision === "REQUIRE_HUMAN") return "warn";
  return "bad";
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{ borderBottom: "1px solid #e5e7eb", paddingBottom: 6 }}>{title}</h3>
      {children}
    </div>
  );
}

function CaseOverview({ caseSummary, authority }: { caseSummary: CaseSummary | null; authority: AuthorityRecord[] }) {
  if (!caseSummary) return <p>Loading case…</p>;
  const latestAuthority = authority[authority.length - 1];
  return (
    <div>
      <Section title="Synthetic order / seller / product">
        <table>
          <tbody>
            <tr><td style={{ paddingRight: 16, color: "#666" }}>Case</td><td>{caseSummary.case_id}</td></tr>
            <tr><td style={{ paddingRight: 16, color: "#666" }}>Order</td><td>{caseSummary.order_ref}</td></tr>
            <tr><td style={{ paddingRight: 16, color: "#666" }}>Seller</td><td>{caseSummary.seller_ref}</td></tr>
            <tr><td style={{ paddingRight: 16, color: "#666" }}>Product</td><td>{caseSummary.product_ref}</td></tr>
            <tr><td style={{ paddingRight: 16, color: "#666" }}>Risk band</td><td>{caseSummary.risk_band}</td></tr>
            <tr><td style={{ paddingRight: 16, color: "#666" }}>State version</td><td>{caseSummary.state_version}</td></tr>
          </tbody>
        </table>
      </Section>
      <Section title="Current state and termination status">
        <Badge tone="neutral">{caseSummary.status}</Badge>
      </Section>
      <Section title="Proposed action versus authority decision">
        {latestAuthority ? (
          <div>
            <p><strong>Proposed action:</strong> {latestAuthority.proposed_action}</p>
            <p>
              <strong>Authority decision:</strong>{" "}
              <Badge tone={decisionTone(latestAuthority.decision)}>{latestAuthority.decision}</Badge>
            </p>
            <p><strong>Reason codes:</strong> {latestAuthority.reason_codes.join(", ")}</p>
          </div>
        ) : (
          <p>No authority record yet.</p>
        )}
      </Section>
      <Section title="Investigation mode">
        <Badge tone="neutral">DETERMINISTIC (offline)</Badge>
        <span style={{ color: "#666", fontSize: 13 }}> — no model API key configured for this run.</span>
      </Section>
    </div>
  );
}

function EvidenceAndClaims({ evidence, claims }: { evidence: Evidence[]; claims: Claim[] }) {
  return (
    <div>
      <Section title="Verified evidence (admitted after validation)">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "#666" }}>
              <th>Source</th><th>Locator</th><th>Authority</th><th>Entity binding</th><th>Support</th><th>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.evidence_id} style={{ borderTop: "1px solid #eee" }}>
                <td>{e.source_id}</td>
                <td>{e.locator}</td>
                <td><Badge tone={e.authority_status === "VALID" ? "good" : "bad"}>{e.authority_status}</Badge></td>
                <td><Badge tone={e.entity_binding_status === "VALID" ? "good" : "bad"}>{e.entity_binding_status}</Badge></td>
                <td><Badge tone={e.support_status === "SUPPORTED" ? "good" : "bad"}>{e.support_status}</Badge></td>
                <td style={{ fontSize: 12, color: "#666" }}>{e.validation_reasons.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Claims (tri-state)">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "#666" }}>
              <th>Claim</th><th>Status</th><th>Reason codes</th><th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.claim_id} style={{ borderTop: "1px solid #eee" }}>
                <td>{c.claim_type}</td>
                <td><Badge tone={claimTone(c.status)}>{c.status}</Badge></td>
                <td style={{ fontSize: 12, color: "#666" }}>{c.reason_codes.join(", ")}</td>
                <td style={{ fontSize: 12 }}>{c.evidence_ids.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

function ReviewQueue({ reviews, onDecided }: { reviews: ReviewTask[]; onDecided: () => void }) {
  const [busy, setBusy] = React.useState<string | null>(null);

  async function decide(review: ReviewTask, decision: string) {
    setBusy(review.review_id);
    try {
      await api.decideReview(review.review_id, {
        reviewer_id: "demo-reviewer",
        decision,
        notes: "Decided from operator UI demo.",
        idempotency_key: `${review.review_id}-${decision}-${Date.now()}`,
      });
      onDecided();
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section title="Pending review tasks">
      {reviews.length === 0 && <p>No review tasks.</p>}
      {reviews.map((r) => (
        <div key={r.review_id} style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: 12, marginBottom: 12 }}>
          <p><strong>{r.review_id}</strong> — case {r.case_id}</p>
          <p style={{ fontSize: 13, color: "#666" }}>Reason: {r.reason_codes.join(", ")}</p>
          <p><Badge tone={r.status === "PENDING" ? "warn" : "neutral"}>{r.status}</Badge> assigned to {r.assigned_role}</p>
          {r.reviewer_decision && (
            <p style={{ fontSize: 13 }}>Reviewer decision: {r.reviewer_decision} ({r.reviewer_id})</p>
          )}
          {r.status === "PENDING" && (
            <div>
              <button disabled={busy === r.review_id} onClick={() => decide(r, "REQUEST_MORE_EVIDENCE")}>
                Request more evidence
              </button>{" "}
              <button disabled={busy === r.review_id} onClick={() => decide(r, "APPROVE_ESCALATION")}>
                Approve escalation
              </button>{" "}
              <button disabled={busy === r.review_id} onClick={() => decide(r, "REJECT_ROUTE")}>
                Reject route
              </button>
              <p style={{ fontSize: 11, color: "#999" }}>No "approve refund" control exists in this demo.</p>
            </div>
          )}
        </div>
      ))}
    </Section>
  );
}

function TraceAndRelease({
  trace,
  release,
  onRunRelease,
  loadingRelease,
}: {
  trace: TraceEvent[];
  release: ReleaseResult | null;
  onRunRelease: () => void;
  loadingRelease: boolean;
}) {
  return (
    <div>
      <Section title="Ordered state transitions and tool calls">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "#666" }}>
              <th>#</th><th>Stage</th><th>Event</th><th>Tool</th>
            </tr>
          </thead>
          <tbody>
            {trace.map((t) => (
              <tr key={t.sequence} style={{ borderTop: "1px solid #eee" }}>
                <td>{t.sequence}</td><td>{t.stage}</td><td>{t.event_type}</td><td>{t.tool_name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Evaluation and release gate">
        <button onClick={onRunRelease} disabled={loadingRelease}>
          {loadingRelease ? "Running R1 + R2…" : "Run release gate (R1 reference + R2 regression fixture)"}
        </button>
        {release && (
          <div style={{ marginTop: 12 }}>
            <p>
              <strong>{release.config_name}:</strong>{" "}
              <Badge tone={release.decision === "PASS" ? "good" : "bad"}>{release.decision}</Badge>
              {" "}critical positives recovered {release.critical_positive_recovered}/{release.critical_positive_total}
              {" "}(Wilson 95% lower bound {release.critical_recall_wilson_lower_bound_95.toFixed(3)})
            </p>
            {release.reason_codes.length > 0 && <p style={{ fontSize: 13, color: "#666" }}>Reasons: {release.reason_codes.join(", ")}</p>}
            {release.regression_fixture_check && (
              <p style={{ marginTop: 8 }}>
                <strong>{release.regression_fixture_check.config_name}</strong> (deliberately degraded regression fixture, not a production result):{" "}
                <Badge tone={release.regression_fixture_check.decision === "PASS" ? "good" : "bad"}>
                  {release.regression_fixture_check.decision}
                </Badge>{" "}
                {release.regression_fixture_check.reason_codes.join(", ")}
              </p>
            )}
          </div>
        )}
      </Section>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = React.useState<Tab>("Case Overview");
  const [caseSummary, setCaseSummary] = React.useState<CaseSummary | null>(null);
  const [claims, setClaims] = React.useState<Claim[]>([]);
  const [evidence, setEvidence] = React.useState<Evidence[]>([]);
  const [authority, setAuthority] = React.useState<AuthorityRecord[]>([]);
  const [trace, setTrace] = React.useState<TraceEvent[]>([]);
  const [reviews, setReviews] = React.useState<ReviewTask[]>([]);
  const [release, setRelease] = React.useState<ReleaseResult | null>(null);
  const [loadingRelease, setLoadingRelease] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const loadCaseData = React.useCallback(async (caseId: string) => {
    const [claimsData, evidenceData, authorityData, traceData, reviewsData] = await Promise.all([
      api.getClaims(caseId),
      api.getEvidence(caseId),
      api.getAuthority(caseId),
      api.getTrace(caseId),
      api.listReviews(),
    ]);
    setClaims(claimsData);
    setEvidence(evidenceData);
    setAuthority(authorityData);
    setTrace(traceData);
    setReviews(reviewsData);
  }, []);

  React.useEffect(() => {
    (async () => {
      try {
        const created = await api.createCase();
        setCaseSummary(created);
        await loadCaseData(created.case_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [loadCaseData]);

  async function runReleaseGate() {
    setLoadingRelease(true);
    try {
      setRelease(await api.getLatestRelease());
    } finally {
      setLoadingRelease(false);
    }
  }

  return (
    <div style={{ fontFamily: "-apple-system, Segoe UI, sans-serif", maxWidth: 1000, margin: "1.5rem auto", padding: "0 1rem" }}>
      <h1 style={{ marginBottom: 4 }}>AI Outcome Assurance</h1>
      <p style={{ color: "#666", marginTop: 0 }}>
        Independent public-retail prototype. Not legal advice, not a production deployment.
      </p>
      {error && <p style={{ color: "#b91c1c" }}>Error: {error} (is the backend running on :8000?)</p>}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, borderBottom: "2px solid #e5e7eb" }}>
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "8px 12px",
              border: "none",
              background: "none",
              borderBottom: tab === t ? "2px solid #111" : "2px solid transparent",
              marginBottom: -2,
              fontWeight: tab === t ? 700 : 400,
              cursor: "pointer",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Case Overview" && <CaseOverview caseSummary={caseSummary} authority={authority} />}
      {tab === "Evidence & Claims" && <EvidenceAndClaims evidence={evidence} claims={claims} />}
      {tab === "Review Queue" && (
        <ReviewQueue reviews={reviews} onDecided={() => caseSummary && loadCaseData(caseSummary.case_id)} />
      )}
      {tab === "Trace & Release" && (
        <TraceAndRelease trace={trace} release={release} onRunRelease={runReleaseGate} loadingRelease={loadingRelease} />
      )}
    </div>
  );
}
