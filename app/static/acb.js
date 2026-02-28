const statusEl = document.getElementById("status");
const acbForm = document.getElementById("acbQuickForm");
const acbSecurityEl = document.getElementById("acbSecurity");
const acbDateEl = document.getElementById("acbDate");
const acbTypeSelectEl = document.getElementById("acbTypeSelect");
const acbAmountEl = document.getElementById("acbAmount");
const acbSharesEl = document.getElementById("acbShares");
const acbCommissionEl = document.getElementById("acbCommission");
const securitiesBody = document.querySelector("#acbSecuritiesTable tbody");

let transactionTypes = [];

function setStatus(message) {
  statusEl.textContent = message;
}

function fmt(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    if (res.status === 401) {
      window.location.assign("/login");
      throw new Error("Authentication required");
    }
    const error = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function renderTypeOptions() {
  acbTypeSelectEl.innerHTML = "";
  transactionTypes.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    acbTypeSelectEl.appendChild(option);
  });
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
      <td><a class="btn-link" href="/security/${encodeURIComponent(row.security)}">Open</a></td>
    `;
    securitiesBody.appendChild(tr);
  });
}

function resetQuickForm() {
  acbAmountEl.value = "";
  acbSharesEl.value = "";
  acbCommissionEl.value = "0";
  acbDateEl.value = new Date().toISOString().slice(0, 10);
}

acbForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    const payload = {
      security: String(acbSecurityEl.value || "").toUpperCase().trim(),
      trade_date: acbDateEl.value,
      transaction_type: acbTypeSelectEl.value,
      amount: Number(acbAmountEl.value || 0),
      shares: Number(acbSharesEl.value || 0),
      commission: Number(acbCommissionEl.value || 0),
    };

    if (!payload.security) {
      throw new Error("Please enter a security symbol.");
    }

    await fetchJson("/api/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    await refreshSecurities();
    resetQuickForm();
    setStatus(`Saved transaction for ${payload.security}.`);
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("acbRefreshBtn").addEventListener("click", async () => {
  try {
    await refreshSecurities();
    setStatus("Refreshed.");
  } catch (err) {
    setStatus(err.message);
  }
});

(async function init() {
  try {
    transactionTypes = await fetchJson("/api/transaction-types");
    renderTypeOptions();
    resetQuickForm();
    await refreshSecurities();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
