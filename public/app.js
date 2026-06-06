(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    userId: "demo-user",
    lastRequestId: null,
    lastRecommendations: null,
    lastDecision: null,
    lastQuery: null,
    lastOpportunityMatch: null,
  };

  function setText(el, value) {
    el.textContent = value == null ? "" : String(value);
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatNumber(v, digits = 2) {
    if (typeof v !== "number" || Number.isNaN(v)) return "—";
    return v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
  }

  function formatCurrency(v, currency) {
    if (typeof v !== "number" || Number.isNaN(v)) return "—";
    if (!currency) return formatNumber(v);
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(v);
    } catch {
      return `${formatNumber(v)} ${currency}`;
    }
  }

  function createRequestId() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") return globalThis.crypto.randomUUID();
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function setLastRequestId(id) {
    state.lastRequestId = id;
    const el = $("#lastRequestId");
    setText(el, id || "—");
    el.title = id || "";
  }

  function showState(el, message) {
    if (!el) return;
    if (!message) {
      el.classList.remove("is-visible");
      el.textContent = "";
      return;
    }
    el.classList.add("is-visible");
    el.textContent = message;
  }

  async function apiRequest(path, { method = "GET", body } = {}) {
    const clientRequestId = createRequestId();
    const headers = { Accept: "application/json", "X-Request-ID": clientRequestId };
    if (body != null) headers["Content-Type"] = "application/json";

    const res = await fetch(path, {
      method,
      headers,
      body: body != null ? JSON.stringify(body) : undefined,
    });
    const serverRequestId = res.headers.get("X-Request-ID") || clientRequestId;
    setLastRequestId(serverRequestId);

    const text = await res.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!res.ok) {
      const err = new Error(typeof payload === "string" ? payload : (payload && payload.detail) || res.statusText);
      err.status = res.status;
      err.payload = payload;
      err.requestId = serverRequestId;
      throw err;
    }
    return payload;
  }

  /* ─── Routing ─── */
  function setRoute(route) {
    $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.route === route));
    $$(".view").forEach((v) => v.classList.toggle("is-hidden", v.dataset.view !== route));
    const title = ({
      dashboard: "Dashboard",
      profile: "Profile",
      knowledge: "Knowledge",
      query: "Query",
      recommendations: "Recommendations",
      opportunities: "Opportunities",
      history: "History",
    })[route] || "Dashboard";
    setText($("#viewTitle"), title);
  }

  function activeUser() {
    return state.userId.trim();
  }

  function setUserId(userId) {
    state.userId = String(userId || "").trim() || "demo-user";
    $("#userId").value = state.userId;
    localStorage.setItem("ai_fc_user_id", state.userId);
    setText($("#activeUserMeta"), `Active user: ${state.userId}`);
  }

  /* ─── Default profile ─── */
  function defaultProfile(userId) {
    return {
      user_id: userId,
      country: "US",
      risk_tolerance: "medium",
      cashflow: { monthly_income: 6000, monthly_expenses: 4200 },
      assets: [{ name: "Checking", category: "cash", value: 8000, liquidity: "high" }],
      liabilities: [{ name: "Credit card", balance: 3500, apr: 19.99, minimum_payment: 120 }],
      goals: [{ name: "Emergency fund", target_amount: 15000, horizon_months: 12, priority: "high" }],
      preferences: { currency: "USD", constraints: ["avoid concentrated positions"] },
    };
  }

  function normalizeConstraintsInput(v) {
    const s = String(v || "").trim();
    if (!s) return [];
    return s
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  }

  /* ─── Editable row table (profile) ─── */
  function rowTable({ columns, rows, onAdd, onChange, onRemove, emptyText }) {
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    for (const col of columns) {
      const th = document.createElement("th");
      th.textContent = col.label;
      trh.appendChild(th);
    }
    const thActions = document.createElement("th");
    thActions.textContent = "";
    trh.appendChild(thActions);
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = columns.length + 1;
      td.className = "muted";
      td.textContent = emptyText || "No items";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      rows.forEach((row, idx) => {
        const tr = document.createElement("tr");
        columns.forEach((col) => {
          const td = document.createElement("td");
          let input;
          if (col.type === "select") {
            input = document.createElement("select");
            input.className = "select";
            col.options.forEach((opt) => {
              const o = document.createElement("option");
              o.value = opt.value;
              o.textContent = opt.label ?? opt.value;
              input.appendChild(o);
            });
            input.value = row[col.key] ?? col.options[0]?.value ?? "";
          } else {
            input = document.createElement("input");
            input.className = "input";
            input.type = col.type || "text";
            input.value = row[col.key] ?? "";
            if (col.type === "number") {
              input.step = "0.01";
              input.min = "0";
            }
          }
          input.addEventListener("change", () => onChange(idx, col.key, input.value));
          td.appendChild(input);
          tr.appendChild(td);
        });

        const tdActions = document.createElement("td");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-ghost";
        btn.textContent = "Remove";
        btn.addEventListener("click", () => onRemove(idx));
        tdActions.appendChild(btn);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
      });
    }

    table.appendChild(tbody);
    return table;
  }

  /* ─── Profile form state ─── */
  const profileForm = {
    model: null,
    assets: [],
    liabilities: [],
    goals: [],
  };

  function loadFormFromProfile(profile) {
    profileForm.model = profile;
    profileForm.assets = Array.isArray(profile.assets) ? profile.assets.map((a) => ({ ...a })) : [];
    profileForm.liabilities = Array.isArray(profile.liabilities) ? profile.liabilities.map((l) => ({ ...l })) : [];
    profileForm.goals = Array.isArray(profile.goals) ? profile.goals.map((g) => ({ ...g })) : [];

    $("#profileCountry").value = profile.country || "US";
    $("#profileCurrency").value = (profile.preferences && profile.preferences.currency) || "USD";
    $("#profileRisk").value = profile.risk_tolerance || "medium";
    $("#profileIncome").value = String((profile.cashflow && profile.cashflow.monthly_income) ?? "");
    $("#profileExpenses").value = String((profile.cashflow && profile.cashflow.monthly_expenses) ?? "");
    
    // Optional: set constraints if element exists (for backward compatibility)
    const constraintsEl = $("#profileConstraints");
    if (constraintsEl) {
      constraintsEl.value = (profile.preferences && Array.isArray(profile.preferences.constraints))
        ? profile.preferences.constraints.join(", ")
        : "";
    }
    
    $("#profileJson").value = JSON.stringify(profile, null, 2);

    renderProfileTables();
  }

  function buildProfileFromForm() {
    const userId = activeUser();
    const country = ($("#profileCountry").value || "US").trim();
    const currency = ($("#profileCurrency").value || "USD").trim().toUpperCase();
    const risk = $("#profileRisk").value;
    const income = Number($("#profileIncome").value || 0);
    const expenses = Number($("#profileExpenses").value || 0);
    
    // Get constraints if element exists, otherwise empty array
    const constraintsEl = $("#profileConstraints");
    const constraints = constraintsEl ? normalizeConstraintsInput(constraintsEl.value) : [];

    const assets = profileForm.assets.map((a) => ({
      name: String(a.name || "").trim(),
      category: a.category || "cash",
      value: Number(a.value || 0),
      liquidity: a.liquidity || "high",
    })).filter((a) => a.name);

    const liabilities = profileForm.liabilities.map((l) => ({
      name: String(l.name || "").trim(),
      balance: Number(l.balance || 0),
      apr: Number(l.apr || 0),
      minimum_payment: Number(l.minimum_payment || 0),
    })).filter((l) => l.name);

    const goals = profileForm.goals.map((g) => ({
      name: String(g.name || "").trim(),
      target_amount: Number(g.target_amount || 0),
      horizon_months: Number(g.horizon_months || 0),
      priority: g.priority || "medium",
    })).filter((g) => g.name);

    const profile = {
      user_id: userId,
      country,
      risk_tolerance: risk,
      cashflow: { monthly_income: income, monthly_expenses: expenses },
      assets,
      liabilities,
      goals,
      preferences: { currency, constraints },
    };
    $("#profileJson").value = JSON.stringify(profile, null, 2);
    return profile;
  }

  function renderProfileTables() {
    const assetsRoot = $("#assetsTable");
    assetsRoot.innerHTML = "";
    assetsRoot.appendChild(
      rowTable({
        columns: [
          { key: "name", label: "Name" },
          { key: "category", label: "Category", type: "select", options: [{ value: "cash" }, { value: "other" }] },
          { key: "value", label: "Value", type: "number" },
          {
            key: "liquidity",
            label: "Liquidity",
            type: "select",
            options: [{ value: "high" }, { value: "medium" }, { value: "low" }],
          },
        ],
        rows: profileForm.assets,
        emptyText: "No assets. Add assets to improve the accuracy of available capital estimates.",
        onChange: (idx, key, value) => {
          profileForm.assets[idx][key] = value;
          $("#profileJson").value = JSON.stringify(buildProfileFromForm(), null, 2);
        },
        onRemove: (idx) => {
          profileForm.assets.splice(idx, 1);
          renderProfileTables();
          $("#profileJson").value = JSON.stringify(buildProfileFromForm(), null, 2);
        },
      })
    );

    const liabRoot = $("#liabilitiesTable");
    liabRoot.innerHTML = "";
    liabRoot.appendChild(
      rowTable({
        columns: [
          { key: "name", label: "Name" },
          { key: "balance", label: "Balance", type: "number" },
          { key: "apr", label: "APR (%)", type: "number" },
          { key: "minimum_payment", label: "Min payment", type: "number" },
        ],
        rows: profileForm.liabilities,
        emptyText: "No liabilities.",
        onChange: (idx, key, value) => {
          profileForm.liabilities[idx][key] = value;
          $("#profileJson").value = JSON.stringify(buildProfileFromForm(), null, 2);
        },
        onRemove: (idx) => {
          profileForm.liabilities.splice(idx, 1);
          renderProfileTables();
          $("#profileJson").value = JSON.stringify(buildProfileFromForm(), null, 2);
        },
      })
    );

    const goalsRoot = $("#goalsTable");
    goalsRoot.innerHTML = "";
    goalsRoot.appendChild(
      rowTable({
        columns: [
          { key: "name", label: "Name" },
          { key: "target_amount", label: "Target", type: "number" },
          { key: "horizon_months", label: "Horizon (months)", type: "number" },
          {
            key: "priority",
            label: "Priority",
            type: "select",
            options: [{ value: "high" }, { value: "medium" }, { value: "low" }],
          },
        ],
        rows: profileForm.goals,
        emptyText: "No goals. Add goals to enable impact and horizon alignment estimates.",
        onChange: (idx, key, value) => {
          profileForm.goals[idx][key] = value;
          $("#profileJson").value = JSON.stringify(buildProfileFromForm(), null, 2);
        },
        onRemove: (idx) => {
          profileForm.goals.splice(idx, 1);
          renderProfileTables();
          $("#profileJson").value = JSON.stringify(buildProfileFromForm(), null, 2);
        },
      })
    );
  }

  /* ─── Rendering helpers ─── */
  function renderKeyValues(root, items) {
    root.innerHTML = "";
    items.forEach(({ k, v }) => {
      const el = document.createElement("div");
      el.className = "kv";
      el.innerHTML = `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div>`;
      root.appendChild(el);
    });
  }

  function renderConstraints(root, constraints) {
    root.innerHTML = "";
    if (!Array.isArray(constraints) || constraints.length === 0) {
      root.innerHTML = `<div class="muted">No constraints detected.</div>`;
      return;
    }
    constraints.forEach((c) => {
      const severity = String(c.severity || "low");
      const badgeClass = severity === "high" ? "badge-danger" : severity === "medium" ? "badge-warning" : "badge-ok";
      const el = document.createElement("div");
      el.className = "kv";
      el.innerHTML = `
        <div class="row" style="justify-content: space-between; align-items: flex-start;">
          <div style="min-width: 0;">
            <div style="font-weight:700; font-size:13px;">${escapeHtml(c.constraint_id || "constraint")}</div>
            <div class="muted" style="margin-top:2px; font-size:13px; line-height: 1.4;">${escapeHtml(c.message || "")}</div>
          </div>
          <span class="badge ${badgeClass}" style="flex-shrink: 0; padding: 2px 10px;">${escapeHtml(severity)}</span>
        </div>
      `;
      root.appendChild(el);
    });
  }

  function renderCitations(root, citations) {
    root.innerHTML = "";
    if (!Array.isArray(citations) || citations.length === 0) {
      root.innerHTML = `<div class="muted">No citations returned.</div>`;
      return;
    }
    citations.forEach((c) => {
      const el = document.createElement("div");
      el.className = "kv";
      el.innerHTML = `
        <div class="k">${escapeHtml(c.title || "Untitled")}</div>
        <div class="v">${escapeHtml(c.source || "—")}</div>
        <div class="muted" style="margin-top:6px; font-family: var(--mono); font-size:12px;">
          doc_id=${escapeHtml(c.doc_id || "—")} · chunk_id=${escapeHtml(c.chunk_id || "—")} · chunk_index=${escapeHtml(c.chunk_index ?? "—")}
        </div>
      `;
      root.appendChild(el);
    });
  }

  function scoreBar(score) {
    const n = typeof score === "number" && !Number.isNaN(score) ? Math.max(0, Math.min(1, score)) : 0;
    const wrap = document.createElement("div");
    const cls = n >= 0.75 ? "scorebar is-strong" : n <= 0.35 ? "scorebar is-weak" : "scorebar";
    wrap.className = cls;
    const fill = document.createElement("span");
    fill.style.width = `${Math.round(n * 100)}%`;
    wrap.appendChild(fill);
    return wrap;
  }

  function formatConstraintCount(constraints) {
    const n = Array.isArray(constraints) ? constraints.length : 0;
    return n === 1 ? "1 constraint" : `${n} constraints`;
  }

  /* ─── Decision trace panel ─── */
  function decisionTracePanel(trace) {
    if (!trace || typeof trace !== "object") return null;

    const input = trace.input_summary && typeof trace.input_summary === "object" ? trace.input_summary : {};
    const filters = Array.isArray(trace.filters_applied) ? trace.filters_applied : [];
    const eligible = Array.isArray(trace.eligible_opportunities) ? trace.eligible_opportunities : [];
    const rejected = Array.isArray(trace.rejected_opportunities) ? trace.rejected_opportunities : [];
    const scoring = Array.isArray(trace.scoring_breakdown) ? trace.scoring_breakdown : [];
    const selected = trace.selected_option_reason || "";
    const alternatives = Array.isArray(trace.alternatives_considered) ? trace.alternatives_considered : [];

    // Build an informative collapsed summary
    const constraints = Array.isArray(input.constraints_detected) ? input.constraints_detected : [];
    const topScored = scoring.length > 0 ? scoring[0] : null;
    const summaryParts = [];

    const wrap = document.createElement("details");
    wrap.className = "details";

    // Build summary line with structured badges
    let summaryHtml = `<summary>Decision trace`;
    summaryHtml += `<span class="trace-summary">`;
    summaryHtml += `<span class="trace-summary-item"><span class="ts-label">Filters</span> ${escapeHtml(String(filters.length))}</span>`;
    summaryHtml += `<span class="trace-summary-item ts-ok"><span class="ts-label">Eligible</span> ${escapeHtml(String(eligible.length))}</span>`;
    if (rejected.length > 0) {
      summaryHtml += `<span class="trace-summary-item ts-danger"><span class="ts-label">Rejected</span> ${escapeHtml(String(rejected.length))}</span>`;
    }
    if (topScored) {
      summaryHtml += `<span class="trace-summary-item ts-warning"><span class="ts-label">Top score</span> ${escapeHtml(formatNumber(Number(topScored.total_score), 2))}</span>`;
    }
    if (selected) {
      const selectedShort = selected.length > 60 ? selected.slice(0, 57) + "…" : selected;
      summaryHtml += `<span class="trace-summary-item"><span class="ts-label">→</span> ${escapeHtml(selectedShort)}</span>`;
    }
    summaryHtml += `</span></summary>`;
    wrap.innerHTML = summaryHtml;

    const body = document.createElement("div");
    body.className = "details-body";

    const inputFacts = [
      { k: "risk_tolerance", v: input.risk_tolerance ?? "—" },
      { k: "available_capital", v: formatNumber(Number(input.estimated_available_capital ?? NaN), 2) },
      { k: "goal_horizon_months", v: input.goal_horizon_months == null ? "—" : String(input.goal_horizon_months) },
    ];

    // Pipeline indicator
    const pipelineHtml = `
      <div class="trace-pipeline">
        <div class="trace-pipeline-step"><span class="trace-pipeline-count">${escapeHtml(String(inputFacts.length))}</span> Input</div>
        <div class="trace-pipeline-step"><span class="trace-pipeline-count">${escapeHtml(String(filters.length))}</span> Filters</div>
        <div class="trace-pipeline-step"><span class="trace-pipeline-count">${escapeHtml(String(eligible.length))}</span> Eligible</div>
        <div class="trace-pipeline-step"><span class="trace-pipeline-count">${escapeHtml(String(rejected.length))}</span> Rejected</div>
        <div class="trace-pipeline-step"><span class="trace-pipeline-count">${escapeHtml(String(scoring.length))}</span> Scoring</div>
        <div class="trace-pipeline-step"><span class="trace-pipeline-count">✓</span> Selected</div>
      </div>
    `;

    const eligibleTable = eligible.length
      ? `
        <table>
          <thead><tr><th>Instrument</th><th>Risk</th><th>Liquidity</th><th>Min capital</th></tr></thead>
          <tbody>
            ${eligible
              .slice(0, 8)
              .map(
                (e) => `
              <tr>
                <td><div style="font-weight:650;">${escapeHtml(e.instrument_name || e.instrument_id)}</div><div class="muted" style="font-family: var(--mono);">${escapeHtml(e.instrument_id || "")}</div></td>
                <td>${escapeHtml(e.risk_level || "—")}</td>
                <td>${escapeHtml(e.liquidity_level || "—")}</td>
                <td>${escapeHtml(formatNumber(Number(e.minimum_capital ?? NaN), 2))}</td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      `
      : `<div class="muted">No eligible opportunities recorded.</div>`;

    const rejectedTable = rejected.length
      ? `
        <table>
          <thead><tr><th>Instrument</th><th>Reasons</th></tr></thead>
          <tbody>
            ${rejected
              .slice(0, 10)
              .map(
                (r) => `
              <tr>
                <td><div style="font-weight:650;">${escapeHtml(r.instrument_name || r.instrument_id)}</div><div class="muted" style="font-family: var(--mono);">${escapeHtml(r.instrument_id || "")}</div></td>
                <td>
                  <div class="reject-reasons">
                    ${(r.reasons || []).map((reason) => `<span class="reject-reason-chip">${escapeHtml(reason)}</span>`).join("")}
                  </div>
                </td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      `
      : `<div class="muted">No rejected opportunities.</div>`;

    const scoringTable = scoring.length
      ? `
        <table>
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Total</th>
              <th>Risk</th>
              <th>Liquidity</th>
              <th>Capital</th>
              <th>Horizon</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${scoring
              .map(
                (s) => {
                  const total = Number(s.total_score);
                  const pct = Math.max(0, Math.min(1, isNaN(total) ? 0 : total));
                  const barClass = pct >= 0.75 ? "scorebar is-strong" : pct <= 0.35 ? "scorebar is-weak" : "scorebar";
                  return `
              <tr>
                <td style="font-family: var(--mono);">${escapeHtml(s.instrument_id || "")}</td>
                <td><strong>${formatNumber(total, 2)}</strong></td>
                <td>${formatNumber(Number(s.risk_score), 2)}</td>
                <td>${formatNumber(Number(s.liquidity_score), 2)}</td>
                <td>${formatNumber(Number(s.capital_score), 2)}</td>
                <td>${formatNumber(Number(s.horizon_alignment_score), 2)}</td>
                <td style="min-width:60px;"><div class="${barClass}"><span style="width:${Math.round(pct * 100)}%"></span></div></td>
              </tr>
            `;
                }
              )
              .join("")}
          </tbody>
        </table>
      `
      : `<div class="muted">No scoring breakdown recorded.</div>`;

    body.innerHTML = `
      ${pipelineHtml}
      <div class="trace-flow">
        <div class="trace-step trace-step--input">
          <div class="trace-step-header">
            <div class="trace-step-title">1 · Input</div>
          </div>
          <div class="trace-step-body">
            <div class="kv-grid" style="margin-top:0;">
              ${inputFacts
                .map((x) => `<div class="kv"><div class="k">${escapeHtml(x.k)}</div><div class="v">${escapeHtml(String(x.v))}</div></div>`)
                .join("")}
            </div>
            <div class="trace-step-note">${escapeHtml(formatConstraintCount(constraints))} detected.</div>
            ${
              constraints.length
                ? `<div class="trace-chips">${constraints
                    .slice(0, 6)
                    .map((c) => `<span class="badge badge-warning">${escapeHtml(c.constraint_id || "constraint")}</span>`)
                    .join("")}</div>`
                : ""
            }
          </div>
        </div>

        <div class="trace-step trace-step--filters">
          <div class="trace-step-header">
            <div class="trace-step-title">2 · Filters applied</div>
            <span class="trace-chip">${escapeHtml(String(filters.length))} filters</span>
          </div>
          <div class="trace-step-body">
            ${
              filters.length
                ? `<ul>${filters.map((f) => `<li>${escapeHtml(f)}</li>`).join("")}</ul>`
                : `<div class="muted">No filters recorded.</div>`
            }
          </div>
        </div>

        <div class="trace-step trace-step--eligible">
          <div class="trace-step-header">
            <div class="trace-step-title">3 · Eligible opportunities</div>
            <span class="trace-chip">${escapeHtml(String(eligible.length))} eligible</span>
          </div>
          <div class="trace-step-body">
            <div class="table-wrap">${eligibleTable}</div>
          </div>
        </div>

        <div class="trace-step trace-step--rejected">
          <div class="trace-step-header">
            <div class="trace-step-title">4 · Rejected</div>
            <span class="trace-chip">${escapeHtml(String(rejected.length))} rejected</span>
          </div>
          <div class="trace-step-body">
            <div class="table-wrap">${rejectedTable}</div>
          </div>
        </div>

        <div class="trace-step trace-step--scoring">
          <div class="trace-step-header">
            <div class="trace-step-title">5 · Scoring breakdown</div>
            <span class="trace-chip">${escapeHtml(String(scoring.length))} scored</span>
          </div>
          <div class="trace-step-body">
            <div class="table-wrap">${scoringTable}</div>
          </div>
        </div>

        <div class="trace-step trace-step--selected">
          <div class="trace-step-header">
            <div class="trace-step-title">6 · Selected</div>
          </div>
          <div class="trace-step-body">
            <div class="prose" style="margin-top:0;">${escapeHtml(selected)}</div>
            ${
              alternatives.length
                ? `<div class="trace-step-note">Alternatives considered: ${escapeHtml(
                    alternatives.map((a) => a.instrument_id || a.instrument_name || "alternative").join(", ")
                  )}</div>`
                : ""
            }
          </div>
        </div>
      </div>
    `;
    wrap.appendChild(body);
    return wrap;
  }

  /* ─── Recommendation card ─── */
  function renderRecommendationCard(rec) {
    const card = document.createElement("div");
    card.className = "rec-card";

    const title = rec.title || "Recommendation";
    const suggestedAmount = rec.suggested_amount != null ? Number(rec.suggested_amount) : null;
    const suggestedCurrency = rec.suggested_currency || (rec.opportunity && rec.opportunity.currency);
    const suggestion = suggestedAmount != null ? formatCurrency(suggestedAmount, suggestedCurrency) : null;

    const risks = Array.isArray(rec.risks) ? rec.risks : [];
    const actions = Array.isArray(rec.actions) ? rec.actions : [];
    const impacted = Array.isArray(rec.impacted_goals) ? rec.impacted_goals : [];
    const projected = rec.projected_impact && typeof rec.projected_impact === "object" ? rec.projected_impact : null;
    const opportunity = rec.opportunity && typeof rec.opportunity === "object" ? rec.opportunity : null;

    const oppBadges = opportunity
      ? `
        <div class="rec-submeta">
          <span class="badge">${escapeHtml(opportunity.asset_class || "asset")}</span>
          <span class="badge">${escapeHtml(opportunity.risk_level || "risk")}</span>
          <span class="badge">${escapeHtml(opportunity.liquidity_level || "liquidity")}</span>
          <span class="badge">${escapeHtml(opportunity.market_country || "")} ${escapeHtml(opportunity.currency || "")}</span>
        </div>
      `
      : "";

    // Suggested amount — prominent callout instead of small badge
    const amountBlock = suggestion
      ? `<div class="rec-amount-callout"><span class="rec-amount-label">Suggested</span> ${escapeHtml(suggestion)}</div>`
      : "";

    const opportunityBody = opportunity
      ? `
        <div class="rec-section">
          <div class="rec-section-title">Opportunity details</div>
          <div class="rec-section-body">
            <div class="muted">
              Min capital: ${escapeHtml(formatCurrency(Number(opportunity.minimum_capital || 0), opportunity.currency))} ·
              Horizon: ${escapeHtml(String(opportunity.investment_horizon?.min_months ?? "—"))}–${escapeHtml(String(opportunity.investment_horizon?.max_months ?? "—"))} months ·
              Expected return: ${escapeHtml(String(opportunity.expected_return_range?.min_annual ?? "—"))}–${escapeHtml(String(opportunity.expected_return_range?.max_annual ?? "—"))} annual
            </div>
          </div>
        </div>
      `
      : "";

    const impactLeft = impacted.length
      ? `
        <div class="callout callout-accent">
          <div class="rec-section-title">Impacted goals</div>
          <div class="rec-section-body table-wrap">
            <table>
              <thead><tr><th>Goal</th><th>Priority</th><th>Time delta</th><th>Probability</th></tr></thead>
              <tbody>
                ${impacted
                  .map(
                    (g) => `
                  <tr>
                    <td>${escapeHtml(g.goal_name || "")}</td>
                    <td>${escapeHtml(g.priority || "")}</td>
                    <td>${escapeHtml(g.time_to_goal_change == null ? "—" : String(g.time_to_goal_change))}</td>
                    <td>${escapeHtml(g.probability_of_success == null ? "—" : formatNumber(Number(g.probability_of_success), 2))}</td>
                  </tr>
                `
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>
      `
      : `
        <div class="callout">
          <div class="rec-section-title">Impacted goals</div>
          <div class="rec-section-body muted">No goal impacts returned for this item.</div>
        </div>
      `;

    const impactRight = projected
      ? `
        <div class="callout callout-accent">
          <div class="rec-section-title">Projected impact</div>
          <div class="rec-section-body">
            <div class="muted">time_delta=${escapeHtml(projected.time_delta == null ? "—" : String(projected.time_delta))} · confidence=${escapeHtml(projected.confidence == null ? "—" : formatNumber(Number(projected.confidence), 2))}</div>
            <div class="muted" style="margin-top:8px; white-space: pre-wrap;">${escapeHtml(projected.explanation || "")}</div>
          </div>
        </div>
      `
      : `
        <div class="callout">
          <div class="rec-section-title">Projected impact</div>
          <div class="rec-section-body muted">No projected impact returned for this item.</div>
        </div>
      `;

    const risksBody = risks.length
      ? `<div class="callout callout-danger rec-risks"><div class="rec-section-title">Risks</div><div class="rec-section-body"><ul>${risks
          .map((r) => `<li>${escapeHtml(r)}</li>`)
          .join("")}</ul></div></div>`
      : "";

    card.innerHTML = `
      <div class="rec-header">
        <div style="min-width:0;">
          <div class="rec-title">${escapeHtml(title)}</div>
          ${oppBadges}
        </div>
        ${amountBlock}
      </div>

      <div class="rec-divider"></div>

      <div class="rec-section">
        <div class="rec-section-title">Rationale</div>
        <div class="rec-section-body" style="white-space: pre-wrap; line-height: 1.55;">${escapeHtml(rec.rationale || "")}</div>
      </div>

      ${
        actions.length
          ? `<div class="rec-section rec-actions"><div class="rec-section-title">Actions</div><div class="rec-section-body"><ul>${actions
              .map((a) => `<li>${escapeHtml(a)}</li>`)
              .join("")}</ul></div></div>`
          : ""
      }

      ${risksBody}
      ${opportunityBody}

      <div class="rec-divider"></div>

      <div class="rec-section">
        <div class="rec-section-title">Outcome and impact</div>
        <div class="rec-section-body rec-impact-grid">
          ${impactLeft}
          ${impactRight}
        </div>
      </div>
    `;

    const trace = rec.decision_trace;
    const panel = decisionTracePanel(trace);
    if (panel) card.appendChild(panel);

    return card;
  }

  function renderRecommendations(root, recommendations, options = {}) {
    root.innerHTML = "";
    if (!Array.isArray(recommendations) || recommendations.length === 0) {
      root.innerHTML = `<div class="muted">No recommendations returned.</div>`;
      return;
    }
    recommendations.forEach((r) => {
      if (options.compact) {
        const el = document.createElement("div");
        el.className = "kv";
        el.style.padding = "10px 12px";
        el.innerHTML = `
          <div class="row" style="justify-content: space-between;">
            <div style="font-weight:700; font-size:13px;">${escapeHtml(r.title || "Recommendation")}</div>
            <div style="font-family:var(--mono); font-size:11px; font-weight:700; color:var(--ok);">${escapeHtml(r.suggested_amount ? formatCurrency(Number(r.suggested_amount), r.suggested_currency) : "")}</div>
          </div>
          <div class="muted" style="font-size:12px; margin-top:4px; line-height:1.4;">${escapeHtml(r.rationale || "").slice(0, 140)}${(r.rationale || "").length > 140 ? "..." : ""}</div>
        `;
        root.appendChild(el);
      } else {
        root.appendChild(renderRecommendationCard(r));
      }
    });
  }

  /* ─── API status ─── */
  async function refreshApiStatus() {
    const el = $("#apiStatus");
    try {
      await apiRequest("/health");
      el.textContent = "ok";
      el.className = "meta-value";
    } catch {
      el.textContent = "error";
      el.className = "meta-value";
    }
  }

  async function loadLatestDecision() {
    const userId = activeUser();
    try {
      const decisions = await apiRequest(`/decisions/${encodeURIComponent(userId)}?limit=1`);
      if (Array.isArray(decisions) && decisions.length > 0) {
        state.lastDecision = decisions[0];
        return decisions[0];
      }
      state.lastDecision = null;
      return null;
    } catch (e) {
      state.lastDecision = null;
      return null;
    }
  }

  /* ─── Dashboard ─── */
  function renderFocusCallout(root, decision) {
    root.innerHTML = "";
    if (!decision) {
      root.innerHTML = `
        <div class="focus-callout">
          <div class="focus-callout-title">Getting started</div>
          <div class="focus-callout-body">
            No decisions found yet. Set up your <strong>Profile</strong>, then go to <strong>Recommendations</strong> to generate your first personalized analysis.
          </div>
        </div>
      `;
      return;
    }

    const ctx = decision.decision_context || {};
    const constraints = Array.isArray(ctx.constraints_detected) ? ctx.constraints_detected : [];
    const recs = Array.isArray(decision.recommendations) ? decision.recommendations : [];
    const topRec = recs.length > 0 ? recs[0] : null;
    const highConstraints = constraints.filter((c) => c.severity === "high");
    const availableCapital = formatNumber(Number(ctx.available_capital ?? NaN), 2);

    let focusText = "";
    if (highConstraints.length > 0) {
      const topConstraint = highConstraints[0];
      focusText += `<strong>Priority constraint:</strong> ${escapeHtml(topConstraint.constraint_id || "constraint")} — ${escapeHtml(topConstraint.message || "")}`;
    }
    if (topRec) {
      if (focusText) focusText += "<br/>";
      focusText += `<strong>Top recommendation:</strong> ${escapeHtml(topRec.title || "—")}`;
    }
    if (availableCapital !== "—") {
      if (focusText) focusText += "<br/>";
      focusText += `Available capital: <span class="focus-metric">${escapeHtml(availableCapital)}</span>`;
    }

    if (!focusText) {
      focusText = "Your financial profile is up to date. Generate new recommendations to get the latest analysis.";
    }

    root.innerHTML = `
      <div class="focus-callout">
        <div class="focus-callout-title">Focus area</div>
        <div class="focus-callout-body">${focusText}</div>
      </div>
    `;
  }

  function renderDashboardFromDecision(decision) {
    const focusRoot = $("#dashFocus");
    const metricsRoot = $("#dashMetrics");
    const constraintsRoot = $("#dashConstraints");
    const recsRoot = $("#dashRecs");

    renderFocusCallout(focusRoot, decision);

    if (!decision) {
      renderKeyValues(metricsRoot, [
        { k: "available_capital", v: "—" },
        { k: "free_cashflow", v: "—" },
        { k: "emergency_fund_months", v: "—" },
        { k: "debt_to_assets_ratio", v: "—" },
      ]);
      renderConstraints(constraintsRoot, []);
      recsRoot.innerHTML = `<div class="muted">No decisions found for this user. Generate recommendations to populate the dashboard.</div>`;
      return;
    }

    const ctx = decision.decision_context || {};
    const fin = ctx.user_financial_state || {};
    const metrics = fin.metrics || {};
    const constraints = Array.isArray(ctx.constraints_detected) ? ctx.constraints_detected : [];

    renderKeyValues(metricsRoot, [
      { k: "available_capital", v: formatNumber(Number(ctx.available_capital ?? NaN), 2) },
      { k: "constraints", v: String(constraints.length) },
      { k: "free_cashflow", v: formatNumber(Number(metrics.free_cashflow ?? NaN), 2) },
      { k: "emergency_fund_months", v: formatNumber(Number(metrics.emergency_fund_months ?? NaN), 2) },
    ]);

    renderConstraints(constraintsRoot, constraints);

    const recs = Array.isArray(decision.recommendations) ? decision.recommendations.slice(0, 3) : [];
    if (!recs.length) {
      recsRoot.innerHTML = `<div class="muted">No recommendations recorded in the most recent decision.</div>`;
      return;
    }
    recsRoot.innerHTML = "";

    // Decision summary header
    const header = document.createElement("div");
    header.className = "kv";
    const createdDate = decision.created_at ? decision.created_at.split("T")[0] : "—";
    header.innerHTML = `
      <div class="k">Last decision</div>
      <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:6px;">
        <span class="badge">${escapeHtml(createdDate)}</span>
        <span class="badge">${escapeHtml(decision.mode || "—")}</span>
        <span class="badge">${escapeHtml(`${recs.length} shown / ${Array.isArray(decision.recommendations) ? decision.recommendations.length : 0} total`)}</span>
        <span class="badge badge-warning">${escapeHtml(formatConstraintCount(constraints))}</span>
      </div>
    `;
    recsRoot.appendChild(header);

    recs.forEach((r) => {
      const el = document.createElement("div");
      el.className = "kv";
      el.innerHTML = `
        <div style="font-weight:650;">${escapeHtml(r.title || "Recommendation")}</div>
        <div class="muted" style="margin-top:6px; line-height:1.5;">${escapeHtml(
          (r.rationale || "").slice(0, 220)
        )}${(r.rationale || "").length > 220 ? "…" : ""}</div>
      `;
      recsRoot.appendChild(el);
    });
  }

  async function onRefresh() {
    await refreshApiStatus();
    const decision = await loadLatestDecision();
    renderDashboardFromDecision(decision);
  }

  /* ─── Profile actions ─── */
  async function onLoadProfile() {
    const userId = activeUser();
    showState($("#profileMsg"), "Loading profile...");
    try {
      const res = await apiRequest(`/profiles/${encodeURIComponent(userId)}`);
      const profile = res.profile;
      loadFormFromProfile(profile);
      showState($("#profileMsg"), "Profile loaded.");
    } catch (e) {
      showState($("#profileMsg"), e.status === 404 ? "Profile not found. You can create it by saving a new profile." : `Failed to load profile: ${e.message}`);
      loadFormFromProfile(defaultProfile(userId));
    }
  }

  async function onSaveProfile() {
    const userId = activeUser();
    showState($("#profileMsg"), "Saving profile...");
    try {
      const profile = buildProfileFromForm();
      await apiRequest(`/profiles/${encodeURIComponent(userId)}`, { method: "PUT", body: { profile } });
      showState($("#profileMsg"), "Profile saved.");
    } catch (e) {
      showState($("#profileMsg"), `Failed to save profile: ${e.message}`);
    }
  }

  function onResetProfile() {
    loadFormFromProfile(defaultProfile(activeUser()));
    showState($("#profileMsg"), "Profile reset to defaults (not saved).");
  }

  function onApplyJsonToForm() {
    try {
      const raw = $("#profileJson").value;
      const profile = JSON.parse(raw);
      profile.user_id = activeUser();
      loadFormFromProfile(profile);
      showState($("#profileMsg"), "Applied JSON to form.");
    } catch (e) {
      showState($("#profileMsg"), "Invalid JSON. Fix the JSON and try again.");
    }
  }

  function onCopyFormToJson() {
    const profile = buildProfileFromForm();
    $("#profileJson").value = JSON.stringify(profile, null, 2);
    showState($("#profileMsg"), "Copied form state to JSON.");
  }

  /* ─── Knowledge ingestion ─── */
  async function onIngestDoc() {
    const title = ($("#docTitle").value || "").trim();
    const source = ($("#docSource").value || "").trim();
    const content = $("#docContent").value || "";
    showState($("#ingestMsg"), "Ingesting...");
    try {
      const res = await apiRequest("/context/ingest", {
        method: "POST",
        body: { title, source: source || null, content },
      });
      showState($("#ingestMsg"), `Ingested doc_id=${res.doc_id} (chunks_indexed=${res.chunks_indexed}).`);
    } catch (e) {
      showState($("#ingestMsg"), `Failed to ingest: ${e.message}`);
    }
  }

  /* ─── Query ─── */
  async function onRunQuery() {
    const userId = activeUser();
    const query = ($("#queryText").value || "").trim();
    const includeRecommendations = $("#includeRecs").checked;
    showState($("#queryState"), "Running query...");
    $("#queryAnswer").textContent = "";
    $("#queryMeta").innerHTML = "";
    $("#queryCitations").innerHTML = "";
    $("#queryRecs").innerHTML = "";

    try {
      const res = await apiRequest("/query", {
        method: "POST",
        body: { user_id: userId, query, include_recommendations: includeRecommendations },
      });
      state.lastQuery = res;
      showState($("#queryState"), "");
      $("#queryAnswer").textContent = res.answer || "";
      renderKeyValues($("#queryMeta"), [
        { k: "mode", v: String(res.mode) },
        { k: "confidence", v: formatNumber(Number(res.confidence), 2) },
        { k: "fallback_used", v: String(Boolean(res.fallback_used)) },
        { k: "fallback_reason", v: res.fallback_reason == null ? "—" : String(res.fallback_reason) },
      ]);
      renderCitations($("#queryCitations"), res.citations);
      renderRecommendations($("#queryRecs"), res.recommendations);
    } catch (e) {
      showState($("#queryState"), `Query failed: ${e.message}`);
    }
  }

  /* ─── Decision context renderer ─── */
  function renderDecisionContext(root, ctx, options = {}) {
    root.innerHTML = "";
    if (!ctx || typeof ctx !== "object") {
      root.innerHTML = `<div class="muted">No decision context returned.</div>`;
      return;
    }

    const isCompact = !!options.compact;
    const decisionId = ctx.decision_id;
    const constraints = Array.isArray(ctx.constraints_detected) ? ctx.constraints_detected : [];
    const reasoning = Array.isArray(ctx.high_level_reasoning) ? ctx.high_level_reasoning : [];
    const opp = ctx.opportunity_engine_summary || null;

    if (!isCompact) {
      const header = document.createElement("div");
      header.className = "kv";
      header.innerHTML = `
        <div class="k">Decision</div>
        <div class="v">${escapeHtml(decisionId || "—")}</div>
        <div class="muted" style="margin-top:8px;">
          Available capital: <strong>${escapeHtml(formatNumber(Number(ctx.available_capital ?? NaN), 2))}</strong>
        </div>
      `;
      root.appendChild(header);
    }

    const grid = document.createElement("div");
    grid.className = isCompact ? "stack" : "kv-grid";
    if (isCompact) grid.style.gap = "8px";
    root.appendChild(grid);

    // Capital & Constraints summary for compact
    if (isCompact) {
      const summary = document.createElement("div");
      summary.className = "row";
      summary.style.justifyContent = "space-between";
      summary.innerHTML = `
        <div class="muted" style="font-size:12px;">Capital: <strong style="color:var(--text);">${escapeHtml(formatNumber(Number(ctx.available_capital ?? NaN), 2))}</strong></div>
        <div class="muted" style="font-size:12px;">${escapeHtml(formatConstraintCount(constraints))}</div>
      `;
      grid.appendChild(summary);
    }

    if (constraints.length > 0) {
      const cBox = document.createElement("div");
      cBox.className = "kv";
      cBox.style.padding = isCompact ? "8px 10px" : "12px";
      cBox.innerHTML = `<div class="k">Constraints</div>`;
      const cRoot = document.createElement("div");
      cRoot.style.marginTop = "6px";
      cBox.appendChild(cRoot);
      grid.appendChild(cBox);
      renderConstraints(cRoot, constraints);
    }

    if (reasoning.length > 0) {
      const rBox = document.createElement("div");
      rBox.className = "kv";
      rBox.style.padding = isCompact ? "8px 10px" : "12px";
      rBox.innerHTML = `<div class="k">Reasoning</div>`;
      const r = document.createElement("div");
      r.className = "prose";
      r.style.fontSize = isCompact ? "12px" : "13px";
      r.style.marginTop = "4px";
      r.innerHTML = `<ul>${reasoning.slice(0, isCompact ? 2 : 5).map((x) => `<li>${escapeHtml(x)}</li>`).join("")}${reasoning.length > (isCompact ? 2 : 5) ? "<li>...</li>" : ""}</ul>`;
      rBox.appendChild(r);
      grid.appendChild(rBox);
    }

    if (opp && !isCompact) {
      const oppBox = document.createElement("div");
      oppBox.className = "kv";
      oppBox.innerHTML = `
        <div class="k">Opportunity engine</div>
        <div class="muted" style="margin-top:8px;">
          eligible=${escapeHtml(String(opp.eligible_count ?? "—"))} · rejected=${escapeHtml(String(opp.rejected_count ?? "—"))}
        </div>
        <div class="muted" style="margin-top:8px; white-space: pre-wrap; font-size:12px;">${escapeHtml(opp.selected_option_reason || "")}</div>
      `;
      grid.appendChild(oppBox);
    }
  }

  /* ─── Recommendations page ─── */
  async function onRunRecommendations() {
    const userId = activeUser();
    const focus = $("#recFocus").value;
    showState($("#recsState"), "Generating recommendations...");
    $("#decisionContext").innerHTML = "";
    $("#recMetrics").innerHTML = "";
    $("#recommendationsList").innerHTML = "";
    try {
      const res = await apiRequest("/recommendations", { method: "POST", body: { user_id: userId, focus } });
      state.lastRecommendations = res;
      showState($("#recsState"), "");
      renderDecisionContext($("#decisionContext"), res.decision_context);
      const metrics = res.metrics || {};
      renderKeyValues($("#recMetrics"), [
        { k: "monthly_income", v: formatNumber(Number(metrics.monthly_income ?? NaN), 2) },
        { k: "monthly_expenses", v: formatNumber(Number(metrics.monthly_expenses ?? NaN), 2) },
        { k: "free_cashflow", v: formatNumber(Number(metrics.free_cashflow ?? NaN), 2) },
        { k: "emergency_fund_months", v: formatNumber(Number(metrics.emergency_fund_months ?? NaN), 2) },
        { k: "high_apr_debt_count", v: String(metrics.high_apr_debt_count ?? "—") },
      ]);
      renderRecommendations($("#recommendationsList"), res.recommendations);
      await onLoadHistory();
      await onRefresh();
    } catch (e) {
      showState($("#recsState"), `Failed to generate recommendations: ${e.message}`);
    }
  }

  /* ─── Opportunities ─── */
  function renderOpportunitiesTable(root, opportunities) {
    root.innerHTML = "";
    if (!Array.isArray(opportunities) || opportunities.length === 0) {
      root.innerHTML = `<div class="muted">No opportunities returned.</div>`;
      return;
    }
    const rows = opportunities
      .map(
        (o) => `
      <tr>
        <td>
          <div style="font-weight:650;">${escapeHtml(o.instrument_name || "")}</div>
          <div class="muted" style="font-family: var(--mono);">${escapeHtml(o.instrument_id || "")}</div>
        </td>
        <td>${escapeHtml(o.asset_class || "")}</td>
        <td>${escapeHtml(o.market_country || "")}</td>
        <td>${escapeHtml(o.currency || "")}</td>
        <td>${escapeHtml(o.risk_level || "")}</td>
        <td>${escapeHtml(o.liquidity_level || "")}</td>
        <td>${escapeHtml(String(o.investment_horizon?.min_months ?? "—"))}–${escapeHtml(String(o.investment_horizon?.max_months ?? "—"))}</td>
        <td>${escapeHtml(String(o.expected_return_range?.min_annual ?? "—"))}–${escapeHtml(String(o.expected_return_range?.max_annual ?? "—"))}</td>
        <td>${escapeHtml(formatNumber(Number(o.minimum_capital ?? NaN), 2))}</td>
      </tr>
    `
      )
      .join("");
    root.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Asset class</th>
            <th>Country</th>
            <th>Currency</th>
            <th>Risk</th>
            <th>Liquidity</th>
            <th>Horizon (m)</th>
            <th>Return (annual)</th>
            <th>Min capital</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  async function onLoadOpportunities() {
    const marketCountry = ($("#oppCountry").value || "").trim();
    const currency = ($("#oppCurrency").value || "").trim();
    const qs = new URLSearchParams();
    if (marketCountry) qs.set("market_country", marketCountry);
    if (currency) qs.set("currency", currency);

    showState($("#oppsState"), "Loading opportunities...");
    $("#oppsTable").innerHTML = "";
    try {
      const res = await apiRequest(`/opportunities${qs.toString() ? `?${qs}` : ""}`);
      showState($("#oppsState"), "");
      renderOpportunitiesTable($("#oppsTable"), res);
    } catch (e) {
      showState($("#oppsState"), `Failed to load opportunities: ${e.message}`);
    }
  }

  async function onMatchOpportunities() {
    const userId = activeUser();
    showState($("#oppsState"), "Matching opportunities...");
    $("#oppsMatches").innerHTML = "";
    try {
      const res = await apiRequest(`/opportunities/match/${encodeURIComponent(userId)}`);
      state.lastOpportunityMatch = res;
      showState($("#oppsState"), "");

      const root = $("#oppsMatches");
      root.innerHTML = "";
      const matches = Array.isArray(res.matches) ? [...res.matches] : [];
      matches.sort((a, b) => Number(b.match_score ?? 0) - Number(a.match_score ?? 0));

      if (!matches.length) {
        root.innerHTML = `<div class="muted">No eligible matches.</div>`;
        const panelEmpty = decisionTracePanel(res.decision_trace);
        if (panelEmpty) root.appendChild(panelEmpty);
        return;
      }

      const summary = document.createElement("div");
      summary.className = "kv";
      summary.innerHTML = `
        <div class="k">Match summary</div>
        <div class="muted" style="margin-top:8px;">
          Showing ${escapeHtml(String(matches.length))} eligible matches, sorted by match score
        </div>
      `;
      root.appendChild(summary);

      const tableWrap = document.createElement("div");
      tableWrap.className = "table-wrap";
      const rows = matches
        .map((m, idx) => {
          const op = m.opportunity || {};
          const score = Number(m.match_score ?? NaN);
          const isTop = idx < 3;
          const highlight = isTop ? ' class="row-highlight row-top"' : "";
          const topBadge = idx === 0 ? `<span class="badge badge-ok">Top</span>` : idx < 3 ? `<span class="badge">Top ${idx + 1}</span>` : "";
          const pct = Math.max(0, Math.min(1, isNaN(score) ? 0 : score));
          const barClass = pct >= 0.75 ? "scorebar is-strong" : pct <= 0.35 ? "scorebar is-weak" : "scorebar";
          const bar = `<div class="${barClass}" style="margin-top:6px;"><span style="width:${Math.round(pct * 100)}%"></span></div>`;
          return `
            <tr${highlight}>
              <td>
                <div style="font-weight:650;">${escapeHtml(op.instrument_name || op.instrument_id || "")} ${topBadge}</div>
                <div class="muted" style="font-family: var(--mono);">${escapeHtml(op.instrument_id || "")}</div>
                <div class="muted" style="margin-top:6px; white-space: pre-wrap;">${escapeHtml(m.match_reason || "")}</div>
              </td>
              <td><span class="badge">${escapeHtml(op.asset_class || "—")}</span></td>
              <td>${escapeHtml(op.risk_level || "—")}</td>
              <td>${escapeHtml(op.liquidity_level || "—")}</td>
              <td>${escapeHtml(String(op.investment_horizon?.min_months ?? "—"))}–${escapeHtml(String(op.investment_horizon?.max_months ?? "—"))}</td>
              <td>
                <div style="font-family: var(--mono); font-weight:700;">${escapeHtml(formatNumber(score, 2))}</div>
                ${bar}
              </td>
            </tr>
          `;
        })
        .join("");
      tableWrap.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Opportunity</th>
              <th>Class</th>
              <th>Risk</th>
              <th>Liquidity</th>
              <th>Horizon (m)</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
      root.appendChild(tableWrap);

      const panel = decisionTracePanel(res.decision_trace);
      if (panel) root.appendChild(panel);
    } catch (e) {
      showState($("#oppsState"), `Failed to match opportunities: ${e.message}`);
    }
  }

  /* ─── Decision history ─── */
  async function onLoadHistory() {
    const userId = activeUser();
    const limit = Number($("#historyLimit").value || 20);
    showState($("#historyState"), "Loading decision history...");
    $("#historyList").innerHTML = "";
    try {
      const decisions = await apiRequest(`/decisions/${encodeURIComponent(userId)}?limit=${encodeURIComponent(String(limit))}`);
      showState($("#historyState"), "");
      if (!Array.isArray(decisions) || decisions.length === 0) {
        $("#historyList").innerHTML = `<div class="muted">No decisions persisted for this user.</div>`;
        return;
      }

      decisions.forEach((d) => {
        const card = document.createElement("details");
        card.className = "history-entry";
        const ctx = d.decision_context || {};
        const constraints = Array.isArray(ctx.constraints_detected) ? ctx.constraints_detected : [];
        const recs = Array.isArray(d.recommendations) ? d.recommendations : [];
        const topRec = recs.length > 0 ? recs[0] : null;
        const createdDate = d.created_at ? d.created_at.split("T")[0] : "—";
        const createdTime = d.created_at && d.created_at.includes("T") ? d.created_at.split("T")[1]?.split(".")[0] || "" : "";
        const availCap = formatNumber(Number(ctx.available_capital ?? NaN), 2);

        card.innerHTML = `
          <summary>
            <span class="history-date">${escapeHtml(createdDate)}${createdTime ? " " + escapeHtml(createdTime) : ""}</span>
            <span class="history-title">${escapeHtml(topRec ? topRec.title : "Decision")}</span>
            <span class="history-badges">
              <span class="badge">${escapeHtml(d.mode || "—")}</span>
              <span class="badge">${escapeHtml(String(recs.length))} recs</span>
              ${constraints.length ? `<span class="badge badge-warning">${escapeHtml(String(constraints.length))}</span>` : ""}
              ${availCap !== "—" ? `<span class="badge">cap: ${escapeHtml(availCap)}</span>` : ""}
            </span>
          </summary>
        `;

        const body = document.createElement("div");
        body.className = "history-body";

        // Integrated history layout
        const grid = document.createElement("div");
        grid.className = "grid-2";
        grid.style.gap = "12px";
        grid.style.marginBottom = "0";
        body.appendChild(grid);

        const leftCol = document.createElement("div");
        leftCol.className = "stack";
        leftCol.style.gap = "8px";
        grid.appendChild(leftCol);

        const rightCol = document.createElement("div");
        rightCol.className = "stack";
        rightCol.style.gap = "8px";
        grid.appendChild(rightCol);

        // Context side
        const ctxTitle = document.createElement("div");
        ctxTitle.className = "history-section-title";
        ctxTitle.textContent = "Decision Context";
        leftCol.appendChild(ctxTitle);
        
        const ctxRoot = document.createElement("div");
        leftCol.appendChild(ctxRoot);
        renderDecisionContext(ctxRoot, ctx, { compact: true });

        // Recommendations side
        const recTitle = document.createElement("div");
        recTitle.className = "history-section-title";
        recTitle.textContent = "Key Recommendations";
        rightCol.appendChild(recTitle);
        
        const recRoot = document.createElement("div");
        rightCol.appendChild(recRoot);
        renderRecommendations(recRoot, recs.slice(0, 3), { compact: true });

        // Add decision trace at the bottom if available
        if (topRec && topRec.decision_trace) {
          const traceTitle = document.createElement("div");
          traceTitle.className = "history-section-title";
          traceTitle.textContent = "Analysis Pipeline";
          body.appendChild(traceTitle);
          
          const tracePanel = decisionTracePanel(topRec.decision_trace);
          if (tracePanel) {
            tracePanel.style.marginTop = "4px";
            body.appendChild(tracePanel);
          }
        }

        card.appendChild(body);
        $("#historyList").appendChild(card);
      });
    } catch (e) {
      showState($("#historyState"), `Failed to load history: ${e.message}`);
    }
  }

  /* ─── Wire events ─── */
  function wireEvents() {
    $$(".nav-item").forEach((b) => b.addEventListener("click", () => setRoute(b.dataset.route)));
    $("#btnSetUser").addEventListener("click", () => setUserId($("#userId").value));
    $("#btnRefresh").addEventListener("click", onRefresh);

    $("#btnLoadProfile").addEventListener("click", onLoadProfile);
    $("#btnSaveProfile").addEventListener("click", onSaveProfile);
    $("#btnResetProfile").addEventListener("click", onResetProfile);
    $("#btnApplyJsonToForm").addEventListener("click", onApplyJsonToForm);
    $("#btnCopyFormToJson").addEventListener("click", onCopyFormToJson);

    $("#btnAddAsset").addEventListener("click", () => {
      profileForm.assets.push({ name: "", category: "cash", value: 0, liquidity: "high" });
      renderProfileTables();
    });
    $("#btnAddLiability").addEventListener("click", () => {
      profileForm.liabilities.push({ name: "", balance: 0, apr: 0, minimum_payment: 0 });
      renderProfileTables();
    });
    $("#btnAddGoal").addEventListener("click", () => {
      profileForm.goals.push({ name: "", target_amount: 0, horizon_months: 12, priority: "medium" });
      renderProfileTables();
    });

    $("#btnIngestDoc").addEventListener("click", onIngestDoc);
    $("#btnRunQuery").addEventListener("click", onRunQuery);
    $("#btnRunRecs").addEventListener("click", onRunRecommendations);

    $("#btnLoadOpps").addEventListener("click", onLoadOpportunities);
    $("#btnMatchOpps").addEventListener("click", onMatchOpportunities);

    $("#btnLoadHistory").addEventListener("click", onLoadHistory);
  }

  /* ─── Bootstrap ─── */
  async function bootstrap() {
    const storedUser = localStorage.getItem("ai_fc_user_id");
    setUserId(storedUser || "demo-user");
    loadFormFromProfile(defaultProfile(activeUser()));
    $("#queryText").value = "How do interest rates affect my decisions this month?";
    $("#oppCountry").value = "US";
    $("#oppCurrency").value = "USD";

    wireEvents();
    setRoute("profile");
    await onRefresh();
  }

  bootstrap();
})();
