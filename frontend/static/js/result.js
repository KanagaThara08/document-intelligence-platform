const API_BASE = "/api/v1";

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function confidenceBadge(confidence) {
  if (confidence === null || confidence === undefined) return "";
  const pct = Math.round(confidence * 100);
  const cls = confidence >= 0.85 ? "confidence-high" : confidence >= 0.6 ? "confidence-med" : "confidence-low";
  return `<span class="confidence-tag ${cls}">${pct}% confidence</span>`;
}

function confidenceBadgeInline(confidence) {
  if (confidence === null || confidence === undefined) return "";
  const pct = Math.round(confidence * 100);
  const cls = confidence >= 0.85 ? "badge-pass" : confidence >= 0.6 ? "badge-na" : "badge-fail";
  return `<span class="badge ${cls}">${pct}% overall confidence</span>`;
}

function renderExtractedData(extracted) {
  if (!extracted) return "<p class='muted'>No extracted data.</p>";
  const internalArrayFields = ["line_items", "asset_components", "liability_equity_components", "comparative_periods"];
  const items = Object.entries(extracted).filter(([k]) => !internalArrayFields.includes(k));

  const cards = items.map(([key, entry]) => {
    let value, meta = "", confidence = null;
    if (entry && typeof entry === "object" && "value" in entry) {
      value = entry.value;
      confidence = entry.confidence ?? null;
      const bits = [];
      if (entry.page_number !== undefined && entry.page_number !== null) bits.push(`p.${entry.page_number}`);
      if (entry.source_text) bits.push(`"${escapeHtml(String(entry.source_text)).slice(0, 60)}"`);
      meta = bits.join(" · ");
    } else if (Array.isArray(entry)) {
      value = `${entry.length} item(s)`;
    } else {
      value = entry;
    }
    const missing = value === null || value === undefined;
    const lowConfidence = confidence !== null && confidence < 0.6;
    const label = key.replace(/_/g, " ");
    return `<div class="kv-item ${missing ? "missing" : ""} ${lowConfidence ? "low-confidence" : ""}">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${missing ? "not found" : escapeHtml(String(value))}</div>
      ${meta ? `<div class="meta">${meta}</div>` : ""}
      ${confidenceBadge(confidence)}
    </div>`;
  }).join("");

  let tableHtml = "";
  if (Array.isArray(extracted.line_items) && extracted.line_items.length) {
    const cols = Array.from(new Set(extracted.line_items.flatMap((li) => Object.keys(li))));
    tableHtml = `<h3 class="section-title" style="margin-top:24px;">Line Items</h3>
      <table><thead><tr>${cols.map((c) => `<th>${escapeHtml(c.replace(/_/g, " "))}</th>`).join("")}</tr></thead>
      <tbody>${extracted.line_items.map((li) => `<tr>${cols.map((c) => `<td data-label="${escapeHtml(c)}">${li[c] !== undefined && li[c] !== null ? escapeHtml(String(li[c])) : "—"}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  let comparativeHtml = "";
  if (Array.isArray(extracted.comparative_periods) && extracted.comparative_periods.length) {
    const labels = extracted.comparative_periods.map((p) => escapeHtml(p.period_label || "comparative")).join(", ");
    comparativeHtml = `<p class="muted" style="margin-top:18px; font-size:0.85rem;">Comparative period(s) also extracted and validated independently: <strong>${labels}</strong>. See the Financial Validation table below and the Raw JSON for full comparative figures.</p>`;
  }

  return `<div class="kv-grid">${cards}</div>${tableHtml}${comparativeHtml}`;
}

function renderValidation(validation) {
  if (!validation || !validation.checks || validation.checks.length === 0) {
    return "<p class='muted'>No validation checks were applicable for this document.</p>";
  }
  const rows = validation.checks.map((c) => {
    const badgeClass = c.status === "PASS" ? "badge-pass" : c.status === "FAIL" ? "badge-fail" : "badge-na";
    return `<tr>
      <td data-label="Check">${escapeHtml(c.name.replace(/_/g, " "))}</td>
      <td data-label="Period" class="muted">${escapeHtml(c.period || "current")}</td>
      <td data-label="Formula" style="font-family: var(--font-mono); font-size: 0.82rem;">${escapeHtml(c.formula)}</td>
      <td data-label="Calculated">${c.calculated_value ?? "—"}</td>
      <td data-label="Reported">${c.reported_value ?? "—"}</td>
      <td data-label="Variance">${c.variance ?? "—"}</td>
      <td data-label="Status"><span class="badge ${badgeClass}">${c.status}</span></td>
    </tr>`;
  }).join("");
  return `<table>
    <thead><tr><th>Check</th><th>Period</th><th>Formula</th><th>Calculated</th><th>Reported</th><th>Variance</th><th>Status</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

async function loadResult() {
  const content = document.getElementById("content");
  try {
    const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(DOCUMENT_NAME)}`);
    const data = await res.json();
    if (!res.ok) {
      content.innerHTML = `<div class="panel"><div class="error-box">${escapeHtml(data.error ? data.error.message : "Document not found.")}</div></div>`;
      return;
    }

    const badgeClass = data.processing_status === "PASS" ? "badge-pass" : "badge-fail";
    const overallConf = data.overall_confidence !== undefined && data.overall_confidence !== null
      ? confidenceBadgeInline(data.overall_confidence) : "";

    let html = `<div class="panel">
      <div class="doc-header">
        <h2>${escapeHtml(data.document_name)}</h2>
        <span class="badge ${badgeClass}">${data.processing_status}</span>
        ${overallConf}
      </div>
      <p class="doc-meta">Type: ${escapeHtml(data.document_type.replace(/_/g, " "))} &middot; Pages: ${data.file_validation?.page_count ?? "—"} &middot; OCR used: ${data.processing_metadata?.ocr_used ?? "—"}</p>
    </div>`;

    if (data.processing_status !== "PASS" && !data.extracted_data) {
      html += `<div class="panel"><div class="error-box">${escapeHtml(data.error ? data.error.message : "Processing failed.")}</div></div>`;
    } else {
      if (data.error) {
        html += `<div class="panel"><div class="error-box">${escapeHtml(data.error.message)}</div></div>`;
      }
      html += `<div class="panel"><h2 class="section-title">Extracted Fields</h2>${renderExtractedData(data.extracted_data)}</div>`;
      html += `<div class="panel"><h2 class="section-title">Financial Validation</h2>${renderValidation(data.validation)}</div>`;
    }

    html += `<div class="panel"><h2 class="section-title">Raw JSON</h2><pre class="json-view">${escapeHtml(JSON.stringify(data, null, 2))}</pre></div>`;

    content.innerHTML = html;
  } catch (err) {
    content.innerHTML = `<div class="panel"><div class="error-box">Failed to load result: ${escapeHtml(String(err))}</div></div>`;
  }
}

loadResult();
