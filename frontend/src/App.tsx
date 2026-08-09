import React from "react";
import { api, AuthorityRecord, Claim, Evidence, ReleaseResult, ReviewTask, TraceEvent, CaseSummary } from "./api";

const TABS = ["Case Overview", "Evidence & Claims", "Review Queue", "Trace & Release"] as const;
type Tab = (typeof TABS)[number];

type Tone = "neutral" | "good" | "warn" | "bad";

function Pill({ children, tone }: { children: React.ReactNode; tone: Tone }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

function claimTone(status: string): Tone {
  if (status === "TRUE") return "good";
  if (status === "UNKNOWN") return "warn";
  return "bad";
}

function decisionTone(decision: string): Tone {
  if (decision === "ALLOW") return "good";
  if (decision === "REQUIRE_HUMAN") return "warn";
  return "bad";
}

function statusTone(status: string): Tone {
  if (status === "COMPLETED") return "good";
  if (status === "NEEDS_REVIEW") return "warn";
  if (status === "CONTROL_BLOCKED" || status === "TECHNICAL_FAILURE") return "bad";
  return "neutral";
}

function Card({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card">
      <div className="card-title-row">
        <h3 className="card-title">{title}</h3>
        {hint && <span className="card-hint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="card">
      <div className="skeleton-line" style={{ width: "40%" }} />
      <div className="skeleton-line" style={{ width: "70%" }} />
      <div className="skeleton-line" style={{ width: "55%" }} />
    </div>
  );
}

function CaseOverview({ caseSummary, authority }: { caseSummary: CaseSummary | null; authority: AuthorityRecord[] }) {
  if (!caseSummary) return <Skeleton />;
  const latestAuthority = authority[authority.length - 1];
  return (
    <div>
      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-tile-label">Case status</div>
          <div className="stat-tile-value">
            <Pill tone={statusTone(caseSummary.status)}>{caseSummary.status}</Pill>
          </div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-label">Authority decision</div>
          <div className="stat-tile-value">
            {latestAuthority ? (
              <Pill tone={decisionTone(latestAuthority.decision)}>{latestAuthority.decision}</Pill>
            ) : (
              <span className="muted">—</span>
            )}
          </div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-label">Investigation mode</div>
          <div className="stat-tile-value">
            <Pill tone="neutral">DETERMINISTIC</Pill>
          </div>
        </div>
      </div>

      <Card title="Synthetic order · seller · product">
        <dl className="kv-grid">
          <dt>Case</dt>
          <dd>{caseSummary.case_id}</dd>
          <dt>Order</dt>
          <dd>{caseSummary.order_ref}</dd>
          <dt>Seller</dt>
          <dd>{caseSummary.seller_ref}</dd>
          <dt>Product</dt>
          <dd>{caseSummary.product_ref}</dd>
          <dt>Risk band</dt>
          <dd>{caseSummary.risk_band}</dd>
          <dt>State version</dt>
          <dd>{caseSummary.state_version}</dd>
        </dl>
      </Card>

      <Card title="Proposed action vs. authority decision">
        {latestAuthority ? (
          <dl className="kv-grid">
            <dt>Proposed action</dt>
            <dd>{latestAuthority.proposed_action}</dd>
            <dt>Decision</dt>
            <dd>
              <Pill tone={decisionTone(latestAuthority.decision)}>{latestAuthority.decision}</Pill>
            </dd>
            <dt>Reason codes</dt>
            <dd>{latestAuthority.reason_codes.join(", ")}</dd>
            <dt>Required role</dt>
            <dd>{latestAuthority.required_role}</dd>
          </dl>
        ) : (
          <p className="muted">No authority record yet.</p>
        )}
      </Card>
    </div>
  );
}

function EvidenceAndClaims({ evidence, claims }: { evidence: Evidence[]; claims: Claim[] }) {
  return (
    <div>
      <Card title="Verified evidence" hint={`${evidence.length} admitted after validation`}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Locator</th>
              <th>Authority</th>
              <th>Entity binding</th>
              <th>Support</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.evidence_id}>
                <td className="mono">{e.source_id}</td>
                <td className="mono">{e.locator}</td>
                <td>
                  <Pill tone={e.authority_status === "VALID" ? "good" : "bad"}>{e.authority_status}</Pill>
                </td>
                <td>
                  <Pill tone={e.entity_binding_status === "VALID" ? "good" : "bad"}>{e.entity_binding_status}</Pill>
                </td>
                <td>
                  <Pill tone={e.support_status === "SUPPORTED" ? "good" : "bad"}>{e.support_status}</Pill>
                </td>
                <td className="muted">{e.validation_reasons.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Claims" hint="tri-state: TRUE / FALSE / UNKNOWN">
        <table className="data-table">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Status</th>
              <th>Reason codes</th>
              <th>Evidence</th>
              <th>Counter-evidence</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.claim_id}>
                <td>{c.claim_type}</td>
                <td>
                  <Pill tone={claimTone(c.status)}>{c.status}</Pill>
                </td>
                <td className="muted">{c.reason_codes.join(", ")}</td>
                <td className="mono muted">{c.evidence_ids.join(", ") || "—"}</td>
                <td className="mono muted">{c.counter_evidence_ids.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ReviewQueue({ reviews, onDecided }: { reviews: ReviewTask[]; onDecided: () => void }) {
  const [busy, setBusy] = React.useState<string | null>(null);

  async function decide(review: ReviewTask, decision: string) {
    setBusy(review.review_id);
    try {
      await api.decideReview(review.review_id, {
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
    <Card title="Pending review tasks" hint={`${reviews.length} total`}>
      {reviews.length === 0 && <p className="empty-state">No review tasks.</p>}
      {reviews.map((r) => (
        <div key={r.review_id} className="review-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <span className="review-id">
              {r.review_id} · {r.case_id}
            </span>
            <Pill tone={r.status === "PENDING" ? "warn" : "neutral"}>{r.status}</Pill>
          </div>
          <p className="muted" style={{ margin: "0 0 6px" }}>
            Reason: {r.reason_codes.join(", ")}
          </p>
          <p className="muted" style={{ margin: 0 }}>
            Assigned to {r.assigned_role}
          </p>
          {r.reviewer_decision && (
            <p style={{ fontSize: 13, marginTop: 8 }}>
              Reviewer decision: <strong>{r.reviewer_decision}</strong> ({r.reviewer_id})
            </p>
          )}
          {r.status === "PENDING" && (
            <div>
              <div className="btn-row">
                <button className="btn" disabled={busy === r.review_id} onClick={() => decide(r, "REQUEST_MORE_EVIDENCE")}>
                  Request more evidence
                </button>
                <button className="btn btn-primary" disabled={busy === r.review_id} onClick={() => decide(r, "APPROVE_ESCALATION")}>
                  Approve escalation
                </button>
                <button className="btn" disabled={busy === r.review_id} onClick={() => decide(r, "REJECT_ROUTE")}>
                  Reject route
                </button>
              </div>
              <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>
                No "approve refund" control exists in this demo.
              </p>
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}

function TraceAndRelease({
  trace,
  traceVerified,
  release,
  onRunRelease,
  loadingRelease,
}: {
  trace: TraceEvent[];
  traceVerified: boolean | null;
  release: ReleaseResult | null;
  onRunRelease: () => void;
  loadingRelease: boolean;
}) {
  return (
    <div>
      <Card
        title="Ordered state transitions and tool calls"
        hint={
          traceVerified === null
            ? `${trace.length} events`
            : `${trace.length} events · hash chain ${traceVerified ? "verified" : "INVALID"}`
        }
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Stage</th>
              <th>Event</th>
              <th>Tool</th>
              <th>Chain hash</th>
            </tr>
          </thead>
          <tbody>
            {trace.map((t) => (
              <tr key={t.sequence}>
                <td className="mono">{t.sequence}</td>
                <td>{t.stage}</td>
                <td>{t.event_type}</td>
                <td className="muted">{t.tool_name ?? "—"}</td>
                <td className="mono muted">{t.state_after_hash ? t.state_after_hash.slice(0, 10) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Evaluation and release gate">
        <button className="btn btn-primary" onClick={onRunRelease} disabled={loadingRelease}>
          {loadingRelease ? "Running R1 + R2…" : "Run release gate (R1 reference + R2 regression fixture)"}
        </button>
        {release && (
          <div style={{ marginTop: 18 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <strong style={{ fontSize: 13.5 }}>{release.config_name}</strong>
              <Pill tone={release.decision === "PASS" ? "good" : "bad"}>{release.decision}</Pill>
            </div>
            <p className="muted" style={{ margin: "0 0 4px" }}>
              Critical positives recovered {release.critical_positive_recovered}/{release.critical_positive_total} ·
              Wilson 95% lower bound {release.critical_recall_wilson_lower_bound_95.toFixed(3)}
            </p>
            {release.reason_codes.length > 0 && (
              <p className="muted" style={{ margin: 0 }}>
                Reasons: {release.reason_codes.join(", ")}
              </p>
            )}
            {release.regression_fixture_check && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--color-border-subtle)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                  <strong style={{ fontSize: 13.5 }}>{release.regression_fixture_check.config_name}</strong>
                  <Pill tone={release.regression_fixture_check.decision === "PASS" ? "good" : "bad"}>
                    {release.regression_fixture_check.decision}
                  </Pill>
                </div>
                <p className="muted" style={{ margin: 0 }}>
                  Deliberately degraded regression fixture, not a production result — {release.regression_fixture_check.reason_codes.join(", ")}
                </p>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

const TAB_ICONS: Record<Tab, React.ReactNode> = {
  "Case Overview": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3.5" y="4" width="17" height="16" rx="2.5" />
      <path d="M8 9h8M8 13h8M8 17h4" strokeLinecap="round" />
    </svg>
  ),
  "Evidence & Claims": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3l7 3.2v5.4c0 4.6-3 8.3-7 9.4-4-1.1-7-4.8-7-9.4V6.2L12 3z" />
      <path d="M9 12l2 2 4-4.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  "Review Queue": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5v5l3.2 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  "Trace & Release": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M4 6h16M4 12h16M4 18h10" strokeLinecap="round" />
      <circle cx="18" cy="18" r="2.4" />
    </svg>
  ),
};

const TAB_META: Record<Tab, { eyebrow: string; subtitle: string }> = {
  "Case Overview": {
    eyebrow: "Case",
    subtitle: "Synthetic order/seller/product timeline, current state, and the proposed action vs. what authority actually decided.",
  },
  "Evidence & Claims": {
    eyebrow: "Investigation",
    subtitle: "Candidate material separated from verified evidence, and every claim resolved to TRUE, FALSE, or UNKNOWN — never guessed.",
  },
  "Review Queue": {
    eyebrow: "Human-in-the-loop",
    subtitle: "Pending review reasons with evidence/claim/authority context. No refund-approval control exists here by design.",
  },
  "Trace & Release": {
    eyebrow: "Audit",
    subtitle: "Ordered trace of every material transition, plus a deterministic release gate run on demand.",
  },
};

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
  const [creatingCase, setCreatingCase] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [caseFixtures, setCaseFixtures] = React.useState<string[]>([]);
  const [selectedFixture, setSelectedFixture] = React.useState("CASE-RET-001");
  const [traceVerified, setTraceVerified] = React.useState<boolean | null>(null);

  const loadCaseData = React.useCallback(async (caseId: string) => {
    const [claimsData, evidenceData, authorityData, traceData, reviewsData, verifyData] = await Promise.all([
      api.getClaims(caseId),
      api.getEvidence(caseId),
      api.getAuthority(caseId),
      api.getTrace(caseId),
      api.listReviews(),
      api.verifyTrace(caseId),
    ]);
    setClaims(claimsData);
    setEvidence(evidenceData);
    setAuthority(authorityData);
    setTrace(traceData);
    setReviews(reviewsData);
    setTraceVerified(verifyData.chain_verified);
  }, []);

  const runNewCase = React.useCallback(
    async (caseId?: string) => {
      setCreatingCase(true);
      setError(null);
      try {
        const created = await api.createCase(caseId ?? selectedFixture);
        setCaseSummary(created);
        await loadCaseData(created.case_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setCreatingCase(false);
      }
    },
    [loadCaseData, selectedFixture],
  );

  React.useEffect(() => {
    api.listCaseFixtures().then((r) => setCaseFixtures(r.case_ids)).catch(() => setCaseFixtures(["CASE-RET-001"]));
    runNewCase("CASE-RET-001");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runReleaseGate() {
    setLoadingRelease(true);
    try {
      setRelease(await api.getLatestRelease());
    } finally {
      setLoadingRelease(false);
    }
  }

  const meta = TAB_META[tab];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" />
          <div>
            <div className="brand-text">AI Outcome Assurance</div>
            <div className="brand-subtext">Synthetic retail prototype</div>
          </div>
        </div>
        <div className="sidebar-section-label">
          Case {caseSummary?.case_id ?? "…"} · v{caseSummary?.state_version ?? "–"}
        </div>
        <nav className="sidebar-nav">
          {TABS.map((t) => (
            <button key={t} className={`nav-item ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
              {TAB_ICONS[t]}
              {t}
            </button>
          ))}
        </nav>
        <div className="sidebar-hint" style={{ padding: "16px 4px 4px" }}>
          Fixture case
        </div>
        <select
          className="case-select"
          value={selectedFixture}
          onChange={(e) => setSelectedFixture(e.target.value)}
        >
          {caseFixtures.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <button
          className="btn btn-primary"
          style={{ margin: "10px 4px 0", width: "calc(100% - 8px)" }}
          onClick={() => runNewCase(selectedFixture)}
          disabled={creatingCase}
        >
          {creatingCase ? "Running…" : "Run selected case"}
        </button>
        <p className="sidebar-hint">
          Runs the deterministic pipeline on the selected fixture and opens a fresh, undecided review
          task (when one is required) so you can try the Review Queue actions again.
        </p>
        <div className="sidebar-footer">
          Independent public-retail prototype.
          <br />
          Not legal advice. Not a production deployment.
        </div>
      </aside>

      <main className="main">
        <div className="page-header">
          <p className="eyebrow">{meta.eyebrow}</p>
          <h1 className="page-title">{tab}</h1>
          <p className="page-subtitle">{meta.subtitle}</p>
        </div>

        {error && <div className="banner">Error: {error} (is the backend running on :8000?)</div>}

        {tab === "Case Overview" && <CaseOverview caseSummary={caseSummary} authority={authority} />}
        {tab === "Evidence & Claims" && <EvidenceAndClaims evidence={evidence} claims={claims} />}
        {tab === "Review Queue" && (
          <ReviewQueue reviews={reviews} onDecided={() => caseSummary && loadCaseData(caseSummary.case_id)} />
        )}
        {tab === "Trace & Release" && (
          <TraceAndRelease
            trace={trace}
            traceVerified={traceVerified}
            release={release}
            onRunRelease={runReleaseGate}
            loadingRelease={loadingRelease}
          />
        )}
      </main>
    </div>
  );
}
