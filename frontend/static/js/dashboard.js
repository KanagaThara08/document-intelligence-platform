const API_BASE = "/api/v1";

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function confidenceCell(confidence) {
  if (confidence === null || confidence === undefined) return "<span class='muted'>—</span>";
  const pct = Math.round(confidence * 100);
  const badgeClass = confidence >= 0.85 ? "badge-pass" : confidence >= 0.6 ? "badge-na" : "badge-fail";
  return `<span class="badge ${badgeClass}">${pct}%</span>`;
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

async function loadDocuments() {
  const tbody = document.getElementById("docTableBody");
  try {
    const res = await fetch(`${API_BASE}/documents`);
    const data = await res.json();
    if (!data.documents || data.documents.length === 0) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="5">No documents processed yet — upload one above to get started.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.documents
      .map((doc) => {
        const badgeClass = doc.processing_status === "PASS" ? "badge-pass" : "badge-fail";
        const when = formatDate(doc.processed_at || doc.created_at);
        return `<tr onclick="window.location.href='/document/${encodeURIComponent(doc.document_name)}'">
          <td data-label="Document">${escapeHtml(doc.document_name)}</td>
          <td data-label="Type">${escapeHtml(doc.document_type)}</td>
          <td data-label="Status"><span class="badge ${badgeClass}">${doc.processing_status}</span></td>
          <td data-label="Confidence">${confidenceCell(doc.overall_confidence)}</td>
          <td data-label="Processed">${escapeHtml(when)}</td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="5">Couldn't load documents: ${escapeHtml(String(err))}</td></tr>`;
  }
}

function setStatus(message, kind) {
  const statusEl = document.getElementById("uploadStatus");
  statusEl.className = `status-line is-${kind}`;
  statusEl.textContent = message;
}

function clearStatus() {
  const statusEl = document.getElementById("uploadStatus");
  statusEl.className = "";
  statusEl.textContent = "";
}

async function processDocument() {
  const fileInput = document.getElementById("fileInput");
  const documentType = document.getElementById("documentType").value;
  const btn = document.getElementById("processBtn");

  if (!fileInput.files.length) {
    setStatus("Choose a PDF, JPG, or PNG file first.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("document_type", documentType);

  btn.disabled = true;
  setStatus("Processing — this can take a few minutes for scanned documents. The table below updates automatically, so you don't need to refresh.", "processing");

  try {
    const res = await fetch(`${API_BASE}/documents/process`, { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok) {
      setStatus(`Done — status: ${data.processing_status}. Opening result…`, "success");
      setTimeout(() => {
        window.location.href = `/document/${encodeURIComponent(data.document_name)}`;
      }, 500);
    } else {
      const msg = data.error ? data.error.message : JSON.stringify(data);
      setStatus(`Failed: ${msg}`, "error");
      loadDocuments();
    }
  } catch (err) {
    setStatus(
      "Still working — this document is taking longer than the connection allowed. " +
      "No need to resubmit: the table below refreshes automatically and will show the result once it's ready.",
      "processing"
    );
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("processBtn").addEventListener("click", processDocument);
loadDocuments();
setInterval(loadDocuments, 8000);