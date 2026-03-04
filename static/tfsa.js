const common = window.FinGlassCommon || {};
const fetchJson = common.fetchJson;
const escapeHtml = common.escapeHtml;
const fmtMoney = common.fmtMoney;
const showConfirmDialog = common.showConfirmDialog;
const showAlertDialog = common.showAlertDialog;
const confirmDialog = (message, options = {}) => {
    if (typeof showConfirmDialog === 'function') {
        return showConfirmDialog(message, options);
    }
    return Promise.resolve(window.confirm(String(message || '')));
};
const alertDialog = (message, options = {}) => {
    if (typeof showAlertDialog === 'function') {
        return showAlertDialog(message, options);
    }
    window.alert(String(message || ''));
    return Promise.resolve(true);
};

function formatMoney(value) {
    if (typeof fmtMoney === 'function') {
        return fmtMoney(value);
    }

    return `$${Number(value || 0).toLocaleString('en-CA', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}`;
}

const tfsaSummaryEl = document.getElementById('tfsa-summary');
const accountSelectEl = document.getElementById('account-select');
const openingWizardSectionEl = document.getElementById('tfsa-opening-wizard-section');
const openingWizardBackdropEl = document.getElementById('tfsaOpeningWizardBackdrop');
const openingWizardFormEl = document.getElementById('tfsa-opening-wizard-form');
const openingWizardInputEl = document.getElementById('tfsa-opening-balance');

const tfsaSettingsSectionEl = document.getElementById('tfsaSettingsSection');
const tfsaSettingsToggleBtnEl = document.getElementById('tfsaSettingsToggleBtn');
const tfsaSettingsBackdropEl = document.getElementById('tfsaSettingsBackdrop');
const tfsaSettingsFormEl = document.getElementById('tfsa-settings-form');
const tfsaSettingsOpeningBalanceInputEl = document.getElementById('tfsa-settings-opening-balance');
const tfsaAnnualLimitFormEl = document.getElementById('tfsa-annual-limit-form');
const tfsaAnnualYearInputEl = document.getElementById('tfsa-annual-year');
const tfsaAnnualAmountInputEl = document.getElementById('tfsa-annual-amount');
const tfsaAnnualLimitsBodyEl = document.getElementById('tfsa-annual-limits-body');
const tfsaResetDataBtnEl = document.getElementById('tfsa-reset-data-btn');
const tfsaResetConfirmModalEl = document.getElementById('tfsaResetConfirmModal');
const tfsaResetConfirmBackdropEl = document.getElementById('tfsaResetConfirmBackdrop');
const tfsaResetConfirmInputEl = document.getElementById('tfsa-reset-confirm-input');
const tfsaResetCancelBtnEl = document.getElementById('tfsa-reset-cancel-btn');
const tfsaResetConfirmBtnEl = document.getElementById('tfsa-reset-confirm-btn');
const tfsaTransactionsBodyEl = document.getElementById('tfsa-transactions-body');
const addAccountFormEl = document.getElementById('add-account-form');
const addContributionFormEl = document.getElementById('add-contribution-form');
const tfsaImportFormEl = document.getElementById('tfsa-import-form');
const tfsaImportFileEl = document.getElementById('tfsa-import-file');
const contributionTypeEl = document.getElementById('contribution-type');
const transferDestinationFieldEl = document.getElementById('transfer-destination-field');
const transferDestinationAccountEl = document.getElementById('transfer-destination-account');

let annualLimits = [];
let minimumAnnualYear = null;
let openingBalanceConfiguredState = false;
let tfsaTransactions = new Map();
let editingTfsaTransactionId = null;
let tfsaAccounts = [];
let totalAvailableRoomState = 0;
let totalRemainingRoomState = 0;
let roomUsedState = 0;
const ROOM_EPSILON = 0.005;

function getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining) {
    const available = Number(totalAvailableRoom || 0);
    const used = Number(roomUsed || 0);
    const remaining = Number(totalRemaining || 0);

    if (available <= ROOM_EPSILON || remaining <= ROOM_EPSILON || (available > ROOM_EPSILON && used >= available - ROOM_EPSILON)) {
        return 'full';
    }
    if (available > ROOM_EPSILON && used > available + ROOM_EPSILON) {
        return 'over-limit';
    }

    const usedRatio = available > ROOM_EPSILON ? (used / available) : 0;
    if (usedRatio >= 0.9) {
        return 'near-limit';
    }

    return null;
}

function buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining) {
    const status = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
    if (!status) {
        return '';
    }

    const labels = {
        'near-limit': 'Near limit',
        'over-limit': 'Over limit',
        full: 'Full'
    };

    const text = labels[status] || '';
    if (!text) {
        return '';
    }

    return `<span class="room-status-label room-status-${status}">${text}</span>`;
}

function getContributionRoomBarColor(status) {
    if (status === 'near-limit') {
        return '#f59e0b';
    }
    if (status === 'full') {
        return '#22c55e';
    }
    if (status === 'over-limit') {
        return '#ef4444';
    }
    return '#3b82f6';
}

async function validateDepositContributionRoom(amount) {
    const normalizedAmount = Number(amount || 0);
    if (!Number.isFinite(normalizedAmount) || normalizedAmount <= 0) {
        return true;
    }

    const available = Number(totalAvailableRoomState || 0);
    const remaining = Number(totalRemainingRoomState || 0);
    const used = Number(roomUsedState || 0);

    if (remaining <= ROOM_EPSILON || normalizedAmount > remaining + ROOM_EPSILON) {
        showError(`This deposit would exceed your contribution room. Remaining room: ${formatMoney(remaining)}.`);
        return false;
    }

    const projectedUsed = used + normalizedAmount;
    const projectedRatio = available > 0 ? (projectedUsed / available) : 1;
    if (projectedRatio >= 0.9) {
        const projectedRemaining = Math.max(0, remaining - normalizedAmount);
        const proceed = await confirmDialog(
            `This deposit brings you near your contribution limit. Projected remaining room: ${formatMoney(projectedRemaining)}. Continue?`,
            {
                title: 'Near contribution limit',
                confirmText: 'Continue',
                cancelText: 'Cancel'
            }
        );
        return Boolean(proceed);
    }

    return true;
}

function setOpeningBalanceInputs(value) {
    const numeric = Number(value || 0);
    if (openingWizardInputEl) {
        openingWizardInputEl.value = numeric.toFixed(2);
    }
    if (tfsaSettingsOpeningBalanceInputEl) {
        tfsaSettingsOpeningBalanceInputEl.value = numeric.toFixed(2);
    }
}

function applyOpeningWizardVisibility(configured) {
    if (!openingWizardSectionEl) {
        return;
    }

    if (configured) {
        openingWizardSectionEl.classList.add('hidden');
        openingWizardSectionEl.setAttribute('aria-hidden', 'true');
        if (openingWizardBackdropEl) {
            openingWizardBackdropEl.classList.add('hidden');
            openingWizardBackdropEl.setAttribute('aria-hidden', 'true');
        }
        return;
    }

    openingWizardSectionEl.classList.remove('hidden');
    openingWizardSectionEl.setAttribute('aria-hidden', 'false');
    if (openingWizardBackdropEl) {
        openingWizardBackdropEl.classList.remove('hidden');
        openingWizardBackdropEl.setAttribute('aria-hidden', 'false');
    }
}

function openTfsaSettingsMenu() {
    if (!tfsaSettingsSectionEl || !tfsaSettingsToggleBtnEl) {
        return;
    }
    tfsaSettingsSectionEl.classList.remove('hidden');
    tfsaSettingsSectionEl.setAttribute('aria-hidden', 'false');
    tfsaSettingsToggleBtnEl.setAttribute('aria-expanded', 'true');
    if (tfsaSettingsBackdropEl) {
        tfsaSettingsBackdropEl.classList.remove('hidden');
        tfsaSettingsBackdropEl.setAttribute('aria-hidden', 'false');
    }
}

function closeTfsaSettingsMenu() {
    if (!tfsaSettingsSectionEl || !tfsaSettingsToggleBtnEl) {
        return;
    }
    tfsaSettingsSectionEl.classList.add('hidden');
    tfsaSettingsSectionEl.setAttribute('aria-hidden', 'true');
    tfsaSettingsToggleBtnEl.setAttribute('aria-expanded', 'false');
    if (tfsaSettingsBackdropEl) {
        tfsaSettingsBackdropEl.classList.add('hidden');
        tfsaSettingsBackdropEl.setAttribute('aria-hidden', 'true');
    }
}

function updateTfsaResetConfirmButtonState() {
    if (!tfsaResetConfirmInputEl || !tfsaResetConfirmBtnEl) {
        return;
    }

    tfsaResetConfirmBtnEl.disabled = tfsaResetConfirmInputEl.value.trim().toUpperCase() !== 'RESET';
}

function openTfsaResetConfirmModal() {
    if (!tfsaResetConfirmModalEl || !tfsaResetConfirmBackdropEl || !tfsaResetConfirmInputEl) {
        return;
    }

    tfsaResetConfirmInputEl.value = '';
    updateTfsaResetConfirmButtonState();
    tfsaResetConfirmModalEl.classList.remove('hidden');
    tfsaResetConfirmModalEl.setAttribute('aria-hidden', 'false');
    tfsaResetConfirmBackdropEl.classList.remove('hidden');
    tfsaResetConfirmBackdropEl.setAttribute('aria-hidden', 'false');
    tfsaResetConfirmInputEl.focus();
}

function closeTfsaResetConfirmModal() {
    if (!tfsaResetConfirmModalEl || !tfsaResetConfirmBackdropEl) {
        return;
    }

    tfsaResetConfirmModalEl.classList.add('hidden');
    tfsaResetConfirmModalEl.setAttribute('aria-hidden', 'true');
    tfsaResetConfirmBackdropEl.classList.add('hidden');
    tfsaResetConfirmBackdropEl.setAttribute('aria-hidden', 'true');
    tfsaResetDataBtnEl?.focus();
}

function setDefaultAnnualYear() {
    if (!tfsaAnnualYearInputEl) {
        return;
    }
    const currentYear = new Date().getFullYear();
    const defaultYear = minimumAnnualYear || currentYear;
    tfsaAnnualYearInputEl.value = String(defaultYear);
}

function applyAnnualYearConstraints(minYear) {
    minimumAnnualYear = Number.isInteger(minYear) ? minYear : null;
    if (!tfsaAnnualYearInputEl) {
        return;
    }

    if (minimumAnnualYear) {
        tfsaAnnualYearInputEl.min = String(minimumAnnualYear);
        const currentValue = Number.parseInt(tfsaAnnualYearInputEl.value || '', 10);
        if (!Number.isInteger(currentValue) || currentValue < minimumAnnualYear) {
            tfsaAnnualYearInputEl.value = String(minimumAnnualYear);
        }
    } else {
        tfsaAnnualYearInputEl.min = '2009';
    }
}

function applyAnnualRoomFormAvailability(isConfigured) {
    const enabled = Boolean(isConfigured);
    if (tfsaAnnualYearInputEl) {
        tfsaAnnualYearInputEl.disabled = !enabled;
    }
    if (tfsaAnnualAmountInputEl) {
        tfsaAnnualAmountInputEl.disabled = !enabled;
    }
    const submitBtn = tfsaAnnualLimitFormEl?.querySelector('button[type="submit"]');
    if (submitBtn) {
        submitBtn.disabled = !enabled;
    }
}

function applyTfsaActionAvailability(isConfigured) {
    const enabled = Boolean(isConfigured);

    if (addAccountFormEl) {
        const fields = addAccountFormEl.querySelectorAll('input, select, button');
        fields.forEach((element) => {
            element.disabled = !enabled;
        });
    }

    if (addContributionFormEl) {
        const fields = addContributionFormEl.querySelectorAll('input, select, button');
        fields.forEach((element) => {
            element.disabled = !enabled;
        });
    }

    if (transferDestinationAccountEl) {
        transferDestinationAccountEl.disabled = !enabled;
    }
}

function applyContributionTypeUi() {
    const isTransfer = contributionTypeEl?.value === 'Transfer';
    if (transferDestinationFieldEl) {
        transferDestinationFieldEl.classList.toggle('hidden', !isTransfer);
    }
    if (transferDestinationAccountEl) {
        transferDestinationAccountEl.required = Boolean(isTransfer);
    }
}

function renderAnnualLimitsTable() {
    if (!tfsaAnnualLimitsBodyEl) {
        return;
    }

    if (!annualLimits.length) {
        tfsaAnnualLimitsBodyEl.innerHTML = '<tr><td colspan="3" class="empty-state">No annual room entries yet.</td></tr>';
        return;
    }

    tfsaAnnualLimitsBodyEl.innerHTML = annualLimits.map((item) => `
        <tr>
            <td>${item.year}</td>
            <td>${formatMoney(Number(item.annual_limit || 0))}</td>
            <td><button type="button" class="btn-small" onclick="deleteTfsaAnnualLimit(${item.year})">Delete</button></td>
        </tr>
    `).join('');
}

function renderTfsaTransactions(rows) {
    if (!tfsaTransactionsBodyEl) {
        return;
    }

        tfsaTransactions = new Map();

    if (!rows.length) {
        tfsaTransactionsBodyEl.innerHTML = '<tr><td colspan="7" class="empty-state">No TFSA transactions yet.</td></tr>';
        return;
    }

        tfsaTransactionsBodyEl.innerHTML = rows.map((row) => {
                tfsaTransactions.set(Number(row.id), row);
                const rowId = Number(row.id);
                const isEditing = editingTfsaTransactionId === rowId;
        const type = String(row.contribution_type || '');
        const amount = Number(row.amount || 0);
        const signedAmount = type === 'Withdrawal' ? -amount : amount;
        const amountDisplay = formatMoney(signedAmount);

                if (isEditing) {
                        const accountOptions = tfsaAccounts.map((account) => {
                                const selected = Number(account.id) === Number(row.tfsa_account_id) ? 'selected' : '';
                                return `<option value="${account.id}" ${selected}>${escapeHtml(account.account_name)}</option>`;
                        }).join('');

                        return `
                                <tr>
                                        <td>${rowId}</td>
                                        <td><input type="date" data-field="contribution_date" data-row-id="${rowId}" value="${escapeHtml(row.contribution_date || '')}" /></td>
                                        <td>
                                            <select data-field="tfsa_account_id" data-row-id="${rowId}">
                                                ${accountOptions}
                                            </select>
                                        </td>
                                        <td>
                                            <select data-field="contribution_type" data-row-id="${rowId}">
                                                <option value="Deposit" ${type === 'Deposit' ? 'selected' : ''}>Deposit</option>
                                                <option value="Withdrawal" ${type === 'Withdrawal' ? 'selected' : ''}>Withdrawal</option>
                                            </select>
                                        </td>
                                        <td><input type="number" step="0.01" min="0.01" data-field="amount" data-row-id="${rowId}" value="${amount.toFixed(2)}" /></td>
                                        <td>
                                            <input type="text" data-field="memo" data-row-id="${rowId}" value="${escapeHtml(row.memo || '')}" />
                                        </td>
                                        <td>
                                            <button type="button" class="edit-tx-btn" data-mode="save" data-id="${rowId}">Save</button>
                                            <button type="button" class="cancel-inline-btn" data-id="${rowId}">Cancel</button>
                                            <button type="button" class="delete-tx-btn" data-id="${rowId}">Delete</button>
                                        </td>
                                </tr>
                        `;
                }

        return `
            <tr>
                                <td>${rowId}</td>
                <td>${escapeHtml(row.contribution_date || '')}</td>
                <td>${escapeHtml(row.account_name || '')}</td>
                <td>${escapeHtml(type)}</td>
                <td>${amountDisplay}</td>
                                <td>${escapeHtml(row.memo || '')}</td>
                                <td>
                                    <button type="button" class="edit-tx-btn" data-mode="edit" data-id="${rowId}">Edit</button>
                                    <button type="button" class="delete-tx-btn" data-id="${rowId}">Delete</button>
                                </td>
            </tr>
        `;
    }).join('');
}

async function loadTfsaTransactions() {
    try {
        const rows = await fetchJson('/api/tfsa/transactions');
        renderTfsaTransactions(Array.isArray(rows) ? rows : []);
    } catch (error) {
        if (tfsaTransactionsBodyEl) {
            tfsaTransactionsBodyEl.innerHTML = `<tr><td colspan="6" class="empty-state">${escapeHtml(error.message || 'Failed to load TFSA transactions')}</td></tr>`;
        }
    }
}

async function saveOpeningBalance(openingBalance) {
    const numeric = Number(openingBalance);
    if (!Number.isFinite(numeric) || numeric < 0) {
        throw new Error('Opening balance must be 0 or greater');
    }

    await fetchJson('/api/tfsa/opening-balance', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ opening_balance: numeric })
    });
}

function initTfsaSettingsMenu() {
    tfsaSettingsToggleBtnEl?.addEventListener('click', () => {
        if (!tfsaSettingsSectionEl) {
            return;
        }
        if (tfsaSettingsSectionEl.classList.contains('hidden')) {
            openTfsaSettingsMenu();
        } else {
            closeTfsaSettingsMenu();
        }
    });

    tfsaSettingsBackdropEl?.addEventListener('click', closeTfsaSettingsMenu);

    tfsaResetConfirmBackdropEl?.addEventListener('click', closeTfsaResetConfirmModal);
    tfsaResetCancelBtnEl?.addEventListener('click', closeTfsaResetConfirmModal);
    tfsaResetConfirmInputEl?.addEventListener('input', updateTfsaResetConfirmButtonState);
    tfsaResetConfirmInputEl?.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter') {
            return;
        }

        event.preventDefault();
        if (!tfsaResetConfirmBtnEl?.disabled) {
            tfsaResetConfirmBtnEl.click();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') {
            return;
        }

        if (tfsaResetConfirmModalEl && !tfsaResetConfirmModalEl.classList.contains('hidden')) {
            closeTfsaResetConfirmModal();
            return;
        }

        closeTfsaSettingsMenu();
    });
}

async function loadTfsaSummary() {
    try {
        const data = await fetchJson('/api/tfsa/summary');

        const openingBalance = Number(data.opening_balance || 0);
        const openingBalanceBaseYear = Number(data.opening_balance_base_year || 0);
        const currentYear = Number(data.current_year || new Date().getFullYear());
        const totalAnnualRoom = Number(data.total_annual_room || 0);
        const totalAvailableRoom = Number(data.total_available_room || 0);
        const roomWithdrawalsPending = Number(data.room_withdrawals_pending || 0);
        const roomUsed = Number(data.room_used || 0);
        const minAnnualYear = Number(data.minimum_annual_year || 0);
        const openingBalanceConfigured = Boolean(data.opening_balance_configured);
        const totalRemaining = Number(data.total_remaining || 0);
        const roomStatus = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
        const roomStatusLabelHtml = buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining);
        const roomBarColor = getContributionRoomBarColor(roomStatus);
        const gaugeWidth = totalAvailableRoom > 0
            ? Math.max(0, Math.min(100, (roomUsed / totalAvailableRoom) * 100))
            : 0;

        totalAvailableRoomState = totalAvailableRoom;
        totalRemainingRoomState = totalRemaining;
        roomUsedState = roomUsed;

        openingBalanceConfiguredState = openingBalanceConfigured;
        applyOpeningWizardVisibility(openingBalanceConfigured);
        applyAnnualRoomFormAvailability(openingBalanceConfigured);
        applyTfsaActionAvailability(openingBalanceConfigured);
        setOpeningBalanceInputs(openingBalance);
        applyAnnualYearConstraints(Number.isInteger(minAnnualYear) && minAnnualYear > 0 ? minAnnualYear : null);
        annualLimits = Array.isArray(data.annual_limits) ? data.annual_limits : [];
        tfsaAccounts = Array.isArray(data.accounts) ? data.accounts : [];
        renderAnnualLimitsTable();

        // Display user-level totals at top
        const totalHtml = `
            <div class="card tfsa-user-total">
                <h3>TFSA Contribution Room Summary</h3>
                <p>Starting Room: <strong>${formatMoney(openingBalance)}</strong></p>
                ${openingBalanceBaseYear > 0 ? `<p>Base Year: <strong>${openingBalanceBaseYear}</strong></p>` : ''}
                <p>Annual Room Added (through ${currentYear}): <strong>${formatMoney(totalAnnualRoom)}</strong></p>
                <p>Total Room Available: <strong>${formatMoney(totalAvailableRoom)}</strong></p>
                <p>Net Room Used: <strong>${formatMoney(roomUsed)}</strong></p>
                <div class="room-gauge">
                    <div class="bar" style="width: ${gaugeWidth}%; background: ${roomBarColor};"></div>
                </div>
                <p class="remaining highlight">Room Remaining: <strong>${formatMoney(totalRemaining)}</strong> ${roomStatusLabelHtml}</p>
                ${roomWithdrawalsPending > 0 ? `<p class="muted">${formatMoney(roomWithdrawalsPending)} of withdrawals will be added back next year.</p>` : ''}
            </div>
        `;

        if (!data.accounts || data.accounts.length === 0) {
            tfsaSummaryEl.innerHTML = totalHtml + '<p>No TFSA accounts yet. Add one below.</p>';
            accountSelectEl.innerHTML = '<option value="">Select Account</option>';
            if (transferDestinationAccountEl) {
                transferDestinationAccountEl.innerHTML = '<option value="">Select Destination Account</option>';
            }
            await loadTfsaTransactions();
            return;
        }

        // Display per-account breakdown
        const accountsHtml = `
            <div class="card tfsa-accounts">
                <h3>Account Contribution Activity</h3>
                <p class="muted">Shows contribution flows only (deposits/withdrawals/transfers), not current market value.</p>
                <div class="table-wrap tfsa-table-wrap">
                    <table class="tfsa-table">
                        <thead>
                            <tr>
                                <th>Account</th>
                                <th>Total Deposits</th>
                                <th>Total Withdrawals</th>
                                <th>Net Contributions</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.accounts.map(acc => `
                                <tr>
                                    <td>${escapeHtml(acc.account_name)}</td>
                                    <td>${formatMoney(Number(acc.deposits || 0))}</td>
                                    <td>${formatMoney(Number(acc.withdrawals || 0))}</td>
                                    <td>${formatMoney(Number(acc.used || 0))}</td>
                                    <td><button class="btn-small" onclick="deleteTfsaAccount(${acc.id})">Delete</button></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        tfsaSummaryEl.innerHTML = totalHtml + accountsHtml;

        // Update account dropdown for adding contributions
        const options = data.accounts.map(acc => `
            <option value="${acc.id}">${escapeHtml(acc.account_name)}</option>
        `).join('');
        accountSelectEl.innerHTML = '<option value="">Select Account</option>' + options;
        if (transferDestinationAccountEl) {
            transferDestinationAccountEl.innerHTML = '<option value="">Select Destination Account</option>' + options;
        }

        await loadTfsaTransactions();
    } catch (error) {
        showError(error.message || 'Failed to load TFSA summary');
    }
}

function showError(msg) {
    alertDialog(`Error: ${msg}`, {
        title: 'Error',
        confirmText: 'OK'
    });
}

addAccountFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set lifetime TFSA room first');
        return;
    }

    const payload = {
        account_name: document.getElementById('account-name').value.trim()
    };

    try {
        await fetchJson('/api/tfsa/accounts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        document.getElementById('add-account-form').reset();
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to add account');
    }
});

addContributionFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set lifetime TFSA room first');
        return;
    }

    const payload = {
        tfsa_account_id: parseInt(accountSelectEl.value),
        contribution_date: document.getElementById('contribution-date').value,
        contribution_type: contributionTypeEl.value,
        amount: parseFloat(document.getElementById('contribution-amount').value),
        memo: document.getElementById('contribution-memo').value.trim()
    };

    if (!payload.tfsa_account_id) {
        showError('Please select an account');
        return;
    }

    if (payload.contribution_type === 'Deposit') {
        const canProceed = await validateDepositContributionRoom(payload.amount);
        if (!canProceed) {
            return;
        }
    }

    try {
        if (payload.contribution_type === 'Transfer') {
            const destinationAccountId = parseInt(transferDestinationAccountEl?.value || '', 10);
            if (!destinationAccountId) {
                showError('Please select destination account');
                return;
            }
            if (destinationAccountId === payload.tfsa_account_id) {
                showError('Source and destination must be different accounts');
                return;
            }

            await fetchJson('/api/tfsa/transfers', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    from_tfsa_account_id: payload.tfsa_account_id,
                    to_tfsa_account_id: destinationAccountId,
                    transfer_date: payload.contribution_date,
                    amount: payload.amount,
                    memo: payload.memo
                })
            });
        } else {
            await fetchJson('/api/tfsa/contributions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
        }

        addContributionFormEl.reset();
        applyContributionTypeUi();
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to add contribution');
    }
});

openingWizardFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    try {
        await saveOpeningBalance(openingWizardInputEl.value);
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to update opening balance');
    }
});

tfsaSettingsFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    try {
        await saveOpeningBalance(tfsaSettingsOpeningBalanceInputEl.value);
        closeTfsaSettingsMenu();
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to update opening balance');
    }
});

tfsaAnnualLimitFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set lifetime TFSA room first');
        return;
    }

    const year = Number.parseInt(tfsaAnnualYearInputEl.value, 10);
    const annualLimit = Number.parseFloat(tfsaAnnualAmountInputEl.value);

    if (!Number.isInteger(year)) {
        showError('Year must be a whole number');
        return;
    }

    if (minimumAnnualYear && year < minimumAnnualYear) {
        showError(`Year must be ${minimumAnnualYear} or later`);
        return;
    }

    if (!Number.isFinite(annualLimit) || annualLimit < 0) {
        showError('Annual room must be 0 or greater');
        return;
    }

    try {
        await fetchJson('/api/tfsa/annual-limits', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                year,
                annual_limit: annualLimit
            })
        });
        tfsaAnnualAmountInputEl.value = '';
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to save annual room');
    }
});

tfsaImportFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const file = tfsaImportFileEl?.files?.[0];
    if (!file) {
        showError('Please select a CSV file to import');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const result = await fetchJson('/api/tfsa/import-csv', {
            method: 'POST',
            body: formData
        });

        tfsaImportFormEl.reset();
        await loadTfsaSummary();

        const parsed = Number(result.parsed || 0);
        const inserted = Number(result.inserted || 0);
        const transfers = Number(result.transfers || 0);
        const skipped = Number(result.skipped || 0);
        const setupRowsParsed = Number(result.setup_rows_parsed || 0);
        const setupAnnualLimitsApplied = Number(result.setup_annual_limits_applied || 0);
        const setupOpeningBalanceApplied = Boolean(result.setup_opening_balance_applied);
        const setupBaseYearApplied = Boolean(result.setup_base_year_applied);
        alertDialog(
            `TFSA import complete. Parsed: ${parsed}, inserted: ${inserted}, transfers: ${transfers}, skipped: ${skipped}. `
            + `Setup rows: ${setupRowsParsed}, opening balance updated: ${setupOpeningBalanceApplied ? 'yes' : 'no'}, `
            + `base year updated: ${setupBaseYearApplied ? 'yes' : 'no'}, annual limits applied: ${setupAnnualLimitsApplied}`,
            {
                title: 'TFSA Import Complete',
                confirmText: 'OK'
            }
        );
    } catch (error) {
        showError(error.message || 'Failed to import TFSA CSV');
    }
});

tfsaResetDataBtnEl?.addEventListener('click', async () => {
    openTfsaResetConfirmModal();
});

tfsaResetConfirmBtnEl?.addEventListener('click', async () => {
    if (tfsaResetConfirmInputEl?.value.trim().toUpperCase() !== 'RESET') {
        showError('Reset cancelled. You must type RESET exactly.');
        return;
    }

    try {
        await fetchJson('/api/tfsa/reset', {
            method: 'POST'
        });
        editingTfsaTransactionId = null;
        tfsaTransactions = new Map();
        closeTfsaResetConfirmModal();
        closeTfsaSettingsMenu();
        await loadTfsaSummary();
        alertDialog('TFSA data reset complete.', {
            title: 'TFSA Reset Complete',
            confirmText: 'OK'
        });
    } catch (error) {
        showError(error.message || 'Failed to reset TFSA data');
    }
});

async function deleteTfsaAnnualLimit(year) {
    if (!(await confirmDialog(`Delete annual room entry for ${year}?`, {
        title: 'Delete Annual Room Entry',
        confirmText: 'Delete',
        cancelText: 'Cancel'
    }))) {
        return;
    }

    try {
        await fetchJson(`/api/tfsa/annual-limits/${year}`, {
            method: 'DELETE'
        });
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to delete annual room');
    }
}

tfsaTransactionsBodyEl?.addEventListener('click', async (event) => {
    const editButton = event.target.closest('.edit-tx-btn');
    const cancelButton = event.target.closest('.cancel-inline-btn');
    const deleteButton = event.target.closest('.delete-tx-btn');

    const targetButton = editButton || cancelButton || deleteButton;
    if (!targetButton) {
        return;
    }

    const transactionId = Number(targetButton.dataset.id);
    if (!Number.isInteger(transactionId) || transactionId <= 0) {
        return;
    }

    if (editButton) {
        const mode = editButton.dataset.mode || 'edit';

        if (mode === 'edit') {
            editingTfsaTransactionId = transactionId;
            renderTfsaTransactions(Array.from(tfsaTransactions.values()));
            return;
        }

        const row = editButton.closest('tr');
        const getField = (name) => row?.querySelector(`[data-field="${name}"]`)?.value || '';

        const payload = {
            contribution_date: getField('contribution_date'),
            tfsa_account_id: parseInt(getField('tfsa_account_id'), 10),
            contribution_type: getField('contribution_type'),
            amount: parseFloat(getField('amount')),
            memo: getField('memo').trim()
        };

        try {
            await fetchJson(`/api/tfsa/transactions/${transactionId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            editingTfsaTransactionId = null;
            await loadTfsaSummary();
        } catch (error) {
            showError(error.message || 'Failed to save TFSA transaction');
        }
        return;
    }

    if (cancelButton) {
        editingTfsaTransactionId = transactionId;
        editingTfsaTransactionId = null;
        renderTfsaTransactions(Array.from(tfsaTransactions.values()));
        return;
    }

    if (deleteButton) {
        if (!(await confirmDialog('Delete this TFSA transaction?', {
            title: 'Delete TFSA Transaction',
            confirmText: 'Delete',
            cancelText: 'Cancel'
        }))) {
            return;
        }

        try {
            await fetchJson(`/api/tfsa/transactions/${transactionId}`, {
                method: 'DELETE'
            });
            editingTfsaTransactionId = null;
            await loadTfsaSummary();
        } catch (error) {
            showError(error.message || 'Failed to delete TFSA transaction');
        }
    }
});

async function deleteTfsaAccount(accountId) {
    if (!(await confirmDialog('Delete this TFSA account and all contributions?', {
        title: 'Delete TFSA Account',
        confirmText: 'Delete Account',
        cancelText: 'Cancel'
    }))) {
        return;
    }

    try {
        await fetchJson(`/api/tfsa/accounts/${accountId}`, {
            method: 'DELETE'
        });
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to delete account');
    }
}

window.deleteTfsaAnnualLimit = deleteTfsaAnnualLimit;

// Load data on page load
initTfsaSettingsMenu();
setDefaultAnnualYear();
applyContributionTypeUi();
contributionTypeEl?.addEventListener('change', applyContributionTypeUi);
loadTfsaSummary();
