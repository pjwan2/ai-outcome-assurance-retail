import React from "react";
import {
  api,
  AgentRunRecord,
  AuthorityRecord,
  Claim,
  Evidence,
  GuardrailReport,
  ReleaseResult,
  ReviewTask,
  TraceEvent,
  CaseSummary,
} from "./api";

const TABS = [
  "Case Overview",
  "Agent Runs",
  "Evidence & Claims",
  "Guardrails",
  "Review Queue",
  "Trace & Release",
] as const;
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
              <th>Relevance</th>
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
                <td>
                  {e.relevance_score === null ? (
                    <span className="muted">—</span>
                  ) : (
                    <Pill tone={e.validation_reasons.includes("LOW_RELEVANCE_RETRIEVAL") ? "warn" : "neutral"}>
                      {e.relevance_score.toFixed(3)}
                    </Pill>
                  )}
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

function agentRunTone(status: string | null): Tone {
  if (status === "COMPLETED") return "good";
  if (status === "CONTROL_BLOCKED" || status === "TECHNICAL_FAILURE") return "bad";
  if (status === "NEEDS_REVIEW" || status === "INSUFFICIENT_EVIDENCE") return "warn";
  return "neutral";
}

function AgentRunCard({ run, indent }: { run: AgentRunRecord; indent: boolean }) {
  return (
    <div className="review-card" style={indent ? { marginLeft: 24 } : undefined}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span className="review-id">{run.agent_id}</span>
        <Pill tone={agentRunTone(run.termination_status)}>{run.termination_status ?? "RUNNING"}</Pill>
      </div>
      <p className="muted" style={{ margin: "0 0 6px" }}>
        Stage {run.stage} · budget {run.tool_calls_used}/{run.max_tool_calls} tool calls,{" "}
        {run.steps_used}/{run.max_steps} steps
      </p>
      {run.termination_reason_codes.length > 0 && (
        <p className="muted" style={{ margin: "0 0 6px" }}>
          Reasons: {run.termination_reason_codes.join(", ")}
        </p>
      )}
      {run.steps.length > 0 && (
        <table className="data-table" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>#</th>
              <th>Step</th>
              <th>Tool</th>
              <th>Candidates</th>
            </tr>
          </thead>
          <tbody>
            {run.steps.map((s) => (
              <tr key={s.sequence}>
                <td className="mono">{s.sequence}</td>
                <td>{s.step_type}</td>
                <td className="muted">{s.tool_name ?? "—"}</td>
                <td className="mono muted">{s.candidate_evidence_ids.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AgentRuns({ agentRuns }: { agentRuns: AgentRunRecord[] }) {
  const roots = agentRuns.filter((r) => !r.parent_run_id);
  const childrenOf = (parentId: string) => agentRuns.filter((r) => r.parent_run_id === parentId);
  const totalToolCalls = agentRuns.reduce((sum, r) => sum + r.tool_calls_used, 0);

  return (
    <div>
      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-tile-label">Agents involved</div>
          <div className="stat-tile-value">{agentRuns.length}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-label">Tool calls used</div>
          <div className="stat-tile-value">{totalToolCalls}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-label">Stage boundary</div>
          <div className="stat-tile-value">
            <Pill tone="neutral">INVESTIGATE only</Pill>
          </div>
        </div>
      </div>

      <Card
        title="Supervised delegation tree"
        hint={`${agentRuns.length} agent run${agentRuns.length === 1 ? "" : "s"}`}
      >
        {agentRuns.length === 0 && <p className="empty-state">No agent runs recorded for this case yet.</p>}
        {roots.map((root) => (
          <React.Fragment key={root.agent_run_id}>
            <AgentRunCard run={root} indent={false} />
            {childrenOf(root.agent_run_id).map((child) => (
              <AgentRunCard key={child.agent_run_id} run={child} indent />
            ))}
          </React.Fragment>
        ))}
      </Card>
      <p className="muted" style={{ margin: "0 0 20px" }}>
        Every run above is confined to INVESTIGATE by a database constraint, not just application code
        — none of it can reach the authority decision (see ADR 0003/0005). Candidates listed here are
        unverified; only the Evidence &amp; Claims tab shows what VALIDATE actually admitted.
      </p>
    </div>
  );
}

function Guardrails({ report }: { report: GuardrailReport | null }) {
  if (!report) return <Skeleton />;
  const relevanceEntries = Object.entries(report.relevance_scores);
  const pillFor = (finding: { category: string }) => (finding.category.startsWith("PII_") ? "warn" : "neutral");

  return (
    <div>
      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-tile-label">Input findings</div>
          <div className="stat-tile-value">{report.input_findings.length}</div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-label">Ungrounded statements blocked</div>
          <div className="stat-tile-value">
            <Pill tone={report.ungrounded_count === 0 ? "good" : "bad"}>{report.ungrounded_count}</Pill>
          </div>
        </div>
        <div className="stat-tile">
          <div className="stat-tile-label">Control boundary</div>
          <div className="stat-tile-value">
            <Pill tone="neutral">Cannot reach AUTHORISE</Pill>
          </div>
        </div>
      </div>

      <Card
        title="Input & retrieval findings"
        hint="prompt-injection categories, PII redactions, TF-IDF relevance — all non-blocking"
      >
        {report.input_findings.length === 0 && relevanceEntries.length === 0 && (
          <p className="empty-state">No guardrail findings for this case.</p>
        )}
        {report.input_findings.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Target</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {report.input_findings.map((f, i) => (
                <tr key={`${f.category}-${f.target}-${i}`}>
                  <td>
                    <Pill tone={pillFor(f)}>{f.category}</Pill>
                  </td>
                  <td className="mono">{f.target}</td>
                  <td className="muted">{f.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {relevanceEntries.length > 0 && (
          <table className="data-table" style={{ marginTop: report.input_findings.length > 0 ? 16 : 0 }}>
            <thead>
              <tr>
                <th>Evidence</th>
                <th>Relevance score</th>
              </tr>
            </thead>
            <tbody>
              {relevanceEntries.map(([evidenceId, score]) => (
                <tr key={evidenceId}>
                  <td className="mono">{evidenceId}</td>
                  <td className="mono">{score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card
        title="Generated case summary (non-authoritative)"
        hint="template-based, groundedness-checked — see ADR 0006"
      >
        {report.summary_sentences.map((s, i) => (
          <p key={i} style={{ margin: "0 0 10px", lineHeight: 1.5 }}>
            <Pill tone={s.grounded ? "good" : "bad"}>{s.grounded ? "GROUNDED" : "BLOCKED"}</Pill>{" "}
            <span className={s.grounded ? undefined : "muted"} style={s.grounded ? undefined : { fontStyle: "italic" }}>
              {s.text}
            </span>
          </p>
        ))}
        <p className="muted" style={{ margin: "10px 0 0" }}>
          Generated by a deterministic template from typed Claims, never from raw evidence text —
          every citation above is independently re-verified against the case's real evidence/claims
          before being shown. A citation that doesn't check out is replaced, not displayed.
        </p>
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
  "Agent Runs": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="5.5" r="2.3" />
      <circle cx="6" cy="18.5" r="2.3" />
      <circle cx="18" cy="18.5" r="2.3" />
      <path d="M12 7.8v4.2M12 12l-5 4.2M12 12l5 4.2" strokeLinecap="round" />
    </svg>
  ),
  "Evidence & Claims": (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3l7 3.2v5.4c0 4.6-3 8.3-7 9.4-4-1.1-7-4.8-7-9.4V6.2L12 3z" />
      <path d="M9 12l2 2 4-4.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Guardrails: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 3.5l6.5 2.6v5c0 4.4-2.7 7.9-6.5 9.1-3.8-1.2-6.5-4.7-6.5-9.1v-5L12 3.5z" />
      <path d="M9.2 12.2l1.9 1.9 3.7-4" strokeLinecap="round" strokeLinejoin="round" />
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
  "Agent Runs": {
    eyebrow: "Multi-agent",
    subtitle: "A supervisor delegates to independent retrieval and critic agents, each a budget-bounded, auditable run confined to INVESTIGATE.",
  },
  "Evidence & Claims": {
    eyebrow: "Investigation",
    subtitle: "Candidate material separated from verified evidence, and every claim resolved to TRUE, FALSE, or UNKNOWN — never guessed.",
  },
  Guardrails: {
    eyebrow: "RAG guardrails",
    subtitle: "Input scanning, PII redaction, retrieval relevance, and a groundedness-checked case summary — none of it can reach the authority decision.",
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
  const [agentRuns, setAgentRuns] = React.useState<AgentRunRecord[]>([]);
  const [guardrailReport, setGuardrailReport] = React.useState<GuardrailReport | null>(null);
  const [reviews, setReviews] = React.useState<ReviewTask[]>([]);
  const [release, setRelease] = React.useState<ReleaseResult | null>(null);
  const [loadingRelease, setLoadingRelease] = React.useState(false);
  const [creatingCase, setCreatingCase] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [caseFixtures, setCaseFixtures] = React.useState<string[]>([]);
  const [selectedFixture, setSelectedFixture] = React.useState("CASE-RET-001");
  const [traceVerified, setTraceVerified] = React.useState<boolean | null>(null);

  const loadCaseData = React.useCallback(async (caseId: string) => {
    const [claimsData, evidenceData, authorityData, traceData, agentRunsData, guardrailData, reviewsData, verifyData] =
      await Promise.all([
        api.getClaims(caseId),
        api.getEvidence(caseId),
        api.getAuthority(caseId),
        api.getTrace(caseId),
        api.getAgentRuns(caseId),
        api.getGuardrails(caseId),
        api.listReviews(),
        api.verifyTrace(caseId),
      ]);
    setClaims(claimsData);
    setEvidence(evidenceData);
    setAuthority(authorityData);
    setTrace(traceData);
    setAgentRuns(agentRunsData);
    setGuardrailReport(guardrailData);
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
        {tab === "Agent Runs" && <AgentRuns agentRuns={agentRuns} />}
        {tab === "Evidence & Claims" && <EvidenceAndClaims evidence={evidence} claims={claims} />}
        {tab === "Guardrails" && <Guardrails report={guardrailReport} />}
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
