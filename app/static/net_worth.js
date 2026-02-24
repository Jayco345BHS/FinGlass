const statusEl = document.getElementById("status");
const netWorthCtx = document.getElementById("netWorthChart");
const netWorthForm = document.getElementById("netWorthForm");
const netWorthDateEl = document.getElementById("netWorthDate");
const netWorthAmountEl = document.getElementById("netWorthAmount");
const netWorthNoteEl = document.getElementById("netWorthNote");
const saveNetWorthBtn = document.getElementById("saveNetWorthBtn");
const cancelNetWorthEditBtn = document.getElementById("cancelNetWorthEditBtn");
const netWorthBody = document.querySelector("#netWorthTable tbody");

let netWorthChart;
let netWorthEntries = [];
let editingNetWorthId = null;

const currencyFormatter = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

if (window.Chart) {
  Chart.defaults.color = "#0f172a";
  Chart.defaults.borderColor = "rgba(15, 23, 42, 0.1)";
}

function setStatus(message) {
  statusEl.textContent = message;
}

function fmtMoney(value) {
  return currencyFormatter.format(Number(value || 0));
}

function moneyTickCallback(value) {
  return fmtMoney(value);
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

function createOrReplaceChart(currentChart, ctx, config) {
  if (currentChart) {
    currentChart.destroy();
  }
  return new Chart(ctx, config);
}

function resetNetWorthForm() {
  editingNetWorthId = null;
  saveNetWorthBtn.textContent = "Add Entry";
  cancelNetWorthEditBtn.classList.add("hidden");
  netWorthForm.reset();
  netWorthDateEl.value = new Date().toISOString().slice(0, 10);
}

function renderNetWorth(entries) {
  netWorthBody.innerHTML = "";

  const tableRows = [...entries].sort((a, b) => b.entry_date.localeCompare(a.entry_date));
  tableRows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.entry_date)}</td>
      <td>${fmtMoney(row.amount)}</td>
      <td>${escapeHtml(row.note || "")}</td>
      <td>
        <button type="button" data-action="edit" data-id="${row.id}">Edit</button>
        <button type="button" data-action="delete" data-id="${row.id}">Delete</button>
      </td>
    `;
    netWorthBody.appendChild(tr);
  });

  const chartRows = [...entries].sort((a, b) => a.entry_date.localeCompare(b.entry_date));
  netWorthChart = createOrReplaceChart(netWorthChart, netWorthCtx, {
    type: "line",
    data: {
      labels: chartRows.map((row) => row.entry_date),
      datasets: [
        {
          label: "Net Worth",
          data: chartRows.map((row) => Number(row.amount || 0)),
          borderColor: "#10b981",
          backgroundColor: "rgba(16, 185, 129, 0.18)",
          fill: true,
          tension: 0.22,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `Net Worth: ${fmtMoney(ctx.raw)}`,
          },
        },
      },
      scales: {
        y: {
          ticks: { callback: moneyTickCallback },
        },
      },
    },
  });
}

async function refreshNetWorthTracker() {
  netWorthEntries = await fetchJson("/api/net-worth");
  renderNetWorth(netWorthEntries);
}

async function submitNetWorthForm(event) {
  event.preventDefault();

  const payload = {
    entry_date: netWorthDateEl.value,
    amount: Number(netWorthAmountEl.value || 0),
    note: netWorthNoteEl.value,
  };

  if (!payload.entry_date) {
    throw new Error("Please provide a date for the net worth entry.");
  }

  if (!Number.isFinite(payload.amount)) {
    throw new Error("Please provide a valid net worth amount.");
  }

  if (editingNetWorthId) {
    await fetchJson(`/api/net-worth/${editingNetWorthId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus("Net worth entry updated.");
  } else {
    await fetchJson("/api/net-worth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setStatus("Net worth entry added.");
  }

  await refreshNetWorthTracker();
  resetNetWorthForm();
}

netWorthForm.addEventListener("submit", async (event) => {
  try {
    await submitNetWorthForm(event);
  } catch (err) {
    setStatus(err.message);
  }
});

cancelNetWorthEditBtn.addEventListener("click", () => {
  resetNetWorthForm();
  setStatus("Net worth edit cancelled.");
});

netWorthBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const entryId = Number(button.dataset.id);
  const action = button.dataset.action;
  const row = netWorthEntries.find((item) => Number(item.id) === entryId);
  if (!row) {
    return;
  }

  try {
    if (action === "edit") {
      editingNetWorthId = entryId;
      netWorthDateEl.value = row.entry_date;
      netWorthAmountEl.value = Number(row.amount || 0).toFixed(2);
      netWorthNoteEl.value = row.note || "";
      saveNetWorthBtn.textContent = "Save Changes";
      cancelNetWorthEditBtn.classList.remove("hidden");
      setStatus(`Editing net worth entry for ${row.entry_date}.`);
      return;
    }

    if (action === "delete") {
      await fetchJson(`/api/net-worth/${entryId}`, {
        method: "DELETE",
      });
      await refreshNetWorthTracker();
      if (editingNetWorthId === entryId) {
        resetNetWorthForm();
      }
      setStatus("Net worth entry deleted.");
    }
  } catch (err) {
    setStatus(err.message);
  }
});

(async function init() {
  try {
    await refreshNetWorthTracker();
    resetNetWorthForm();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
