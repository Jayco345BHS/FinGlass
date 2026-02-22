const statusEl = document.getElementById("status");
const securitiesBody = document.querySelector("#securitiesTable tbody");
const csvFileInput = document.getElementById("csvFileInput");
const importTypeSelect = document.getElementById("importTypeSelect");
const importReviewSection = document.getElementById("importReviewSection");
const importReviewBody = document.querySelector("#importReviewTable tbody");
const acbBySecurityCtx = document.getElementById("acbBySecurityChart");

let acbBySecurityChart;
let transactionTypes = [];
let currentImportBatchId = null;
let currentImportRows = [];

function setStatus(message) {
  statusEl.textContent = message;
}

function fmt(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function refreshSecurities() {
  const rows = await fetchJson("/api/securities");
  securitiesBody.innerHTML = "";

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.security}</td>
      <td>${fmt(row.share_balance, 6)}</td>
      <td>${fmt(row.acb)}</td>
      <td>${fmt(row.acb_per_share, 6)}</td>
      <td>${fmt(row.realized_capital_gain)}</td>
      <td>${row.transaction_count}</td>
      <td><a class="btn-link" href="/security/${encodeURIComponent(row.security)}">View</a></td>
    `;
    securitiesBody.appendChild(tr);
  });

  return rows;
}

function renderCharts(securities) {
  if (acbBySecurityChart) {
    acbBySecurityChart.destroy();
  }

  const securityLabels = securities.map((item) => item.security);
  const totalShares = securities.reduce(
    (sum, item) => sum + Number(item.share_balance || 0),
    0,
  );
  const allocationData = securities.map((item) => {
    if (totalShares <= 0) {
      return 0;
    }
    return (Number(item.share_balance || 0) / totalShares) * 100;
  });

  acbBySecurityChart = new Chart(acbBySecurityCtx, {
    type: "doughnut",
    data: {
      labels: securityLabels,
      datasets: [
        {
          label: "Allocation %",
          data: allocationData,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: {
            label(context) {
              const value = Number(context.raw || 0).toFixed(2);
              return `${context.label}: ${value}%`;
            },
          },
        },
      },
    },
  });
}

function renderImportTypeSelect(selected, rowId) {
  return `<select data-field="transaction_type" data-id="${rowId}">${transactionTypes
    .map((type) => `<option value="${escapeHtml(type)}" ${type === selected ? "selected" : ""}>${escapeHtml(type)}</option>`)
    .join("")}</select>`;
}

function renderImportReview(rows) {
  importReviewBody.innerHTML = "";
  currentImportRows = rows;

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="date" data-field="trade_date" data-id="${row.id}" value="${escapeHtml(row.trade_date)}" /></td>
      <td><input type="text" data-field="security" data-id="${row.id}" value="${escapeHtml(row.security)}" /></td>
      <td>${renderImportTypeSelect(row.transaction_type, row.id)}</td>
      <td><input type="number" step="0.0001" data-field="amount" data-id="${row.id}" value="${escapeHtml(row.amount)}" /></td>
      <td><input type="number" step="0.000001" data-field="shares" data-id="${row.id}" value="${escapeHtml(row.shares)}" /></td>
      <td><input type="number" step="0.0001" data-field="commission" data-id="${row.id}" value="${escapeHtml(row.commission)}" /></td>
      <td><button class="remove-import-row-btn" data-id="${row.id}" type="button">Remove</button></td>
    `;
    importReviewBody.appendChild(tr);
  });

  importReviewSection.style.display = rows.length ? "block" : "none";
}

function collectReviewRowPayload(rowId) {
  const getValue = (field) => {
    const el = importReviewBody.querySelector(`[data-field='${field}'][data-id='${rowId}']`);
    return el ? el.value : "";
  };

  return {
    security: String(getValue("security") || "").toUpperCase(),
    trade_date: getValue("trade_date"),
    transaction_type: getValue("transaction_type"),
    amount: Number(getValue("amount") || 0),
    shares: Number(getValue("shares") || 0),
    commission: Number(getValue("commission") || 0),
  };
}

async function loadReviewFromBatch(batchId) {
  const data = await fetchJson(`/api/import/review/${batchId}`);
  currentImportBatchId = batchId;
  renderImportReview(data.rows);
}

async function refreshOverview() {
  const securities = await refreshSecurities();
  renderCharts(securities);
}

async function loadFileForReview(file) {
  if (!file) {
    throw new Error("Please choose a file first.");
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("import_type", importTypeSelect.value);

  const result = await fetchJson("/api/import/review", {
    method: "POST",
    body: formData,
  });

  currentImportBatchId = result.batch.id;
  renderImportReview(result.rows);
  setStatus(`Loaded ${result.rows.length} row(s) for review.`);
}

async function commitReviewImport() {
  if (!currentImportBatchId) {
    throw new Error("No import review loaded.");
  }

  const rowIds = currentImportRows.map((row) => row.id);
  for (const rowId of rowIds) {
    const payload = collectReviewRowPayload(rowId);
    await fetchJson(`/api/import/review/${currentImportBatchId}/rows/${rowId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  const summary = await fetchJson(`/api/import/review/${currentImportBatchId}/commit`, {
    method: "POST",
  });

  currentImportBatchId = null;
  currentImportRows = [];
  renderImportReview([]);
  await refreshOverview();
  setStatus(`Import committed. Parsed ${summary.parsed}, inserted ${summary.inserted}.`);
}

async function importCsv(file) {
  if (!file) {
    throw new Error("Please choose a CSV file first.");
  }

  const formData = new FormData();
  formData.append("file", file);

  const result = await fetchJson("/api/import-csv", {
    method: "POST",
    body: formData,
  });

  setStatus(`CSV import complete. Parsed ${result.parsed}, inserted ${result.inserted}.`);
}

document.getElementById("importCsvBtn").addEventListener("click", () => {
  const importType = importTypeSelect.value;
  if (importType === "tax_pdf") {
    csvFileInput.accept = ".pdf,application/pdf";
  } else {
    csvFileInput.accept = ".csv,text/csv";
  }
  csvFileInput.value = "";
  csvFileInput.click();
});

csvFileInput.addEventListener("change", async () => {
  try {
    const file = csvFileInput.files[0];
    if (!file) {
      return;
    }
    await loadFileForReview(file);
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("commitImportBtn").addEventListener("click", async () => {
  try {
    await commitReviewImport();
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("discardImportBtn").addEventListener("click", () => {
  currentImportBatchId = null;
  currentImportRows = [];
  renderImportReview([]);
  setStatus("Import review discarded.");
});

importReviewBody.addEventListener("click", async (event) => {
  const removeButton = event.target.closest(".remove-import-row-btn");
  if (!removeButton || !currentImportBatchId) {
    return;
  }

  try {
    const rowId = Number(removeButton.dataset.id);
    await fetchJson(`/api/import/review/${currentImportBatchId}/rows/${rowId}`, {
      method: "DELETE",
    });
    await loadReviewFromBatch(currentImportBatchId);
    setStatus(`Removed import row ${rowId}.`);
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("refreshBtn").addEventListener("click", async () => {
  try {
    await refreshOverview();
    setStatus("Refreshed.");
  } catch (err) {
    setStatus(err.message);
  }
});

(async function init() {
  try {
    transactionTypes = await fetchJson("/api/transaction-types");
    await refreshOverview();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
