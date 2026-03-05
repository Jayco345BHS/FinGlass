// Import Wizard - Guided file import experience
const { fetchJson, escapeHtml, defaultCurrencyFormatter, markTableBodyRefreshed } = window.FinGlassCommon || {};
const common = window.FinGlassCommon || {};
const applyPageEnterMotion = common.applyPageEnterMotion;
const WIZARD_MOTION_MS = 220;

// State
let currentStep = 1;
let selectedImportType = null;
let uploadedFile = null;
let parsedData = null;
let batchId = null;

// DOM Elements
const wizardSteps = document.querySelectorAll('.wizard-step');
const stepContents = document.querySelectorAll('.wizard-step-content');
const backBtn = document.getElementById('backBtn');
const nextBtn = document.getElementById('nextBtn');
const submitBtn = document.getElementById('submitBtn');
const importTypeCards = document.querySelectorAll('.import-type-card');
const fileInput = document.getElementById('fileInput');
const dropzone = document.getElementById('dropzone');
const fileInfo = document.getElementById('fileInfo');
const uploadError = document.getElementById('uploadError');
const formatRequirements = document.getElementById('formatRequirements');
const templateDownload = document.getElementById('templateDownload');
const previewTableHead = document.getElementById('previewTableHead');
const previewTableBody = document.getElementById('previewTableBody');
const previewStats = document.getElementById('previewStats');
const previewWarnings = document.getElementById('previewWarnings');
const completionMessage = document.getElementById('completionMessage');
const importAnotherBtn = document.getElementById('importAnotherBtn');

// Import type configurations
const importTypeConfig = {
  transactions: {
    title: 'Investment Transactions',
    fileTypes: ['.csv'],
    accept: 'text/csv,.csv',
    description: 'Upload your broker\'s activity report CSV file',
    requirements: `
      <h4>Required CSV Columns:</h4>
      <ul>
        <li><code>transaction_date</code> - Trade date (YYYY-MM-DD or YYYY-MMM-DD)</li>
        <li><code>symbol</code> - Stock ticker symbol</li>
        <li><code>activity_type</code> - Transaction type: Trade, ReturnOfCapital, Dividend, etc.</li>
        <li><code>activity_sub_type</code> - For trades: BUY or SELL</li>
        <li><code>quantity</code> - Number of shares</li>
        <li><code>net_cash_amount</code> - Total transaction amount</li>
        <li><code>commission</code> - Trading fees (optional)</li>
      </ul>
    `,
    templateName: 'transactions_template.csv',
    endpoint: '/api/import/review',
    subtype: 'activities_csv'
  },
  holdings: {
    title: 'Holdings Snapshot',
    fileTypes: ['.csv'],
    accept: 'text/csv,.csv',
    description: 'Upload your broker\'s portfolio holdings CSV file',
    requirements: `
      <h4>Required CSV Columns:</h4>
      <ul>
        <li><code>Symbol</code> - Stock ticker symbol</li>
        <li><code>Account Number</code> - Your account number</li>
        <li><code>Account Name</code> - Account name/description</li>
        <li><code>Account Type</code> - Account type (RRSP, TFSA, etc.)</li>
        <li><code>Quantity</code> - Number of shares held</li>
        <li><code>Market Price</code> - Current market price per share</li>
        <li><code>Market Value</code> - Total market value</li>
        <li><code>Book Value (CAD)</code> - Original purchase cost</li>
      </ul>
    `,
    templateName: 'holdings_template.csv',
    endpoint: '/api/import/holdings-csv',
    direct: true
  },
  'credit-card': {
    title: 'Credit Card Transactions',
    fileTypes: ['.csv'],
    accept: 'text/csv,.csv',
    description: 'Upload your credit card statement CSV file',
    requirements: `
      <h4>Supported Formats:</h4>
      <ul>
        <li><strong>Rogers Bank Mastercard:</strong> Download transaction history from online banking</li>
        <li>File should include: Transaction Date, Posted Date, Description, Amount, Category</li>
        <li>Categories are automatically normalized for tracking</li>
      </ul>
    `,
    templateName: 'credit_card_template.csv',
    endpoint: '/api/import/credit-card/rogers-csv',
    direct: true
  },
  'tax-pdf': {
    title: 'Tax Documents',
    fileTypes: ['.pdf'],
    accept: 'application/pdf,.pdf',
    description: 'Upload your T3/T5 tax slip PDF file',
    requirements: `
      <h4>Supported Documents:</h4>
      <ul>
        <li><strong>Return of Capital (ROC):</strong> Box 42 from T3 slips</li>
        <li><strong>Reinvested Capital Gains:</strong> From T3/T5 slips</li>
        <li>PDF will be automatically parsed for relevant transactions</li>
        <li>Security symbol should be in the PDF filename (e.g., "VDY-T3-2024.pdf")</li>
      </ul>
    `,
    endpoint: '/api/import/review',
    subtype: 'tax_pdf'
  }
};

// Initialize
function init() {
  applyPageEnterMotion?.({ selector: ".page-header, .card, .wizard-step", maxItems: 12, staggerMs: 18 });
  setupEventListeners();
  renderStep(1);
}

function setupEventListeners() {
  // Import type selection
  importTypeCards.forEach(card => {
    card.addEventListener('click', () => selectImportType(card.dataset.type));
  });

  // Navigation
  backBtn.addEventListener('click', () => goToStep(currentStep - 1));
  nextBtn.addEventListener('click', () => goToStep(currentStep + 1));
  submitBtn.addEventListener('click', submitImport);
  importAnotherBtn.addEventListener('click', () => {
    resetWizard();
    goToStep(1);
  });

  // File upload
  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('dragover', handleDragOver);
  dropzone.addEventListener('dragleave', handleDragLeave);
  dropzone.addEventListener('drop', handleDrop);
  fileInput.addEventListener('change', handleFileSelect);
}

function setAnimatedVisibility(element, visible, displayValue = 'block') {
  if (!element) {
    return;
  }

  if (element.__wizardHideTimer) {
    clearTimeout(element.__wizardHideTimer);
    element.__wizardHideTimer = null;
  }

  if (visible) {
    element.style.display = displayValue;
    requestAnimationFrame(() => {
      element.classList.remove('wizard-motion-hidden');
    });
    return;
  }

  element.classList.add('wizard-motion-hidden');
  element.__wizardHideTimer = setTimeout(() => {
    if (element.classList.contains('wizard-motion-hidden')) {
      element.style.display = 'none';
    }
    element.__wizardHideTimer = null;
  }, WIZARD_MOTION_MS);
}

function selectImportType(type) {
  selectedImportType = type;

  // Update UI
  importTypeCards.forEach(card => {
    card.classList.toggle('selected', card.dataset.type === type);
  });

  // Enable next button
  nextBtn.style.display = 'inline-block';
}

function goToStep(step) {
  if (step < 1 || step > 4) return;

  // Validate before proceeding
  if (step > currentStep) {
    if (currentStep === 1 && !selectedImportType) {
      showError('Please select an import type');
      return;
    }
    if (currentStep === 2 && !uploadedFile) {
      showError('Please upload a file');
      return;
    }
  }

  currentStep = step;
  renderStep(step);
}

function renderStep(step) {
  // Update step indicators
  wizardSteps.forEach((stepEl, index) => {
    const stepNum = index + 1;
    stepEl.classList.remove('active', 'completed');

    if (stepNum === step) {
      stepEl.classList.add('active');
    } else if (stepNum < step) {
      stepEl.classList.add('completed');
    }
  });

  // Show/hide step content
  stepContents.forEach((content, index) => {
    setAnimatedVisibility(content, index + 1 === step, 'block');
  });

  // Update navigation buttons
  backBtn.style.display = step > 1 && step < 4 ? 'inline-block' : 'none';
  nextBtn.style.display = 'none';
  submitBtn.style.display = 'none';

  if (step === 1) {
    nextBtn.style.display = selectedImportType ? 'inline-block' : 'none';
  } else if (step === 2) {
    setupStep2();
    if (uploadedFile) {
      nextBtn.style.display = 'inline-block';
    }
  } else if (step === 3) {
    submitBtn.style.display = 'inline-block';
    renderPreview();
  }
}

function setupStep2() {
  const config = importTypeConfig[selectedImportType];

  document.getElementById('step2Title').textContent = `Upload ${config.title}`;
  document.getElementById('step2Description').textContent = config.description;

  formatRequirements.innerHTML = config.requirements;

  // Set file input accept attribute
  fileInput.setAttribute('accept', config.accept);

  // Template download (if applicable)
  if (config.templateName && selectedImportType !== 'tax-pdf') {
    templateDownload.innerHTML = `
      <a href="/api/import/template/${selectedImportType}" class="download-template-link" download="${config.templateName}">
        📥 Download Template File
      </a>
    `;
  } else {
    templateDownload.innerHTML = '';
  }

  // Reset file state when coming back to this step
  if (!uploadedFile) {
    setAnimatedVisibility(dropzone, true, 'block');
    setAnimatedVisibility(fileInfo, false, 'block');
    setAnimatedVisibility(uploadError, false, 'block');
  }
}

function handleDragOver(e) {
  e.preventDefault();
  dropzone.classList.add('drag-over');
}

function handleDragLeave(e) {
  e.preventDefault();
  dropzone.classList.remove('drag-over');
}

function handleDrop(e) {
  e.preventDefault();
  dropzone.classList.remove('drag-over');

  const files = e.dataTransfer.files;
  if (files.length > 0) {
    processFile(files[0]);
  }
}

function handleFileSelect(e) {
  const files = e.target.files;
  if (files.length > 0) {
    processFile(files[0]);
  }
}

async function processFile(file) {
  uploadedFile = file;
  setAnimatedVisibility(uploadError, false, 'block');

  const config = importTypeConfig[selectedImportType];
  const fileExt = '.' + file.name.split('.').pop().toLowerCase();

  // Validate file type
  if (!config.fileTypes.includes(fileExt)) {
    showError(`Invalid file type. Expected: ${config.fileTypes.join(', ')}`);
    uploadedFile = null;
    return;
  }

  // Show file info
  setAnimatedVisibility(dropzone, false, 'block');
  setAnimatedVisibility(fileInfo, true, 'block');
  // Build file info DOM safely without using innerHTML
  fileInfo.innerHTML = '';

  const infoContainer = document.createElement('div');
  infoContainer.classList.add('file-info');

  const iconEl = document.createElement('div');
  iconEl.classList.add('file-info-icon');
  iconEl.textContent = fileExt === '.pdf' ? '📄' : '📊';
  infoContainer.appendChild(iconEl);

  const detailsEl = document.createElement('div');
  detailsEl.classList.add('file-info-details');

  const nameEl = document.createElement('div');
  nameEl.classList.add('file-info-name');
  // Using textContent ensures the file name is not interpreted as HTML
  nameEl.textContent = file.name;
  detailsEl.appendChild(nameEl);

  const metaEl = document.createElement('div');
  metaEl.classList.add('file-info-meta');
  metaEl.textContent = `${formatFileSize(file.size)} • ${fileExt.toUpperCase().substring(1)}`;
  detailsEl.appendChild(metaEl);

  infoContainer.appendChild(detailsEl);

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.classList.add('btn-secondary');
  removeBtn.textContent = 'Remove';
  removeBtn.addEventListener('click', clearFile);
  infoContainer.appendChild(removeBtn);

  fileInfo.appendChild(infoContainer);

  // Parse file
  try {
    await parseFile(file);
    nextBtn.style.display = 'inline-block';
  } catch (error) {
    showError(error.message || 'Failed to parse file');
    uploadedFile = null;
  }
}

async function parseFile(file) {
  const config = importTypeConfig[selectedImportType];
  const formData = new FormData();
  formData.append('file', file);

  if (config.subtype) {
    formData.append('import_type', config.subtype);
  }

  const result = await fetchJson(config.endpoint, {
    method: 'POST',
    body: formData,
    credentials: 'include'
  });

  // Handle different response formats
  if (config.direct) {
    // Direct import (holdings, credit card)
    parsedData = result;
    if (result.rows) {
      parsedData = { rows: result.rows, imported: result.imported || 0 };
    }
  } else {
    // Staged import (transactions, tax PDF)
    // Response format: { batch: {...}, rows: [...] }
    batchId = result.batch?.id || result.batch_id;
    parsedData = { rows: result.rows || [], batch: result.batch };
  }
}

function renderPreview() {
  if (!parsedData) return;

  const config = importTypeConfig[selectedImportType];

  // For direct imports, show summary
  if (config.direct) {
    const rowCount = parsedData.rows?.length || parsedData.imported || 0;
    previewStats.innerHTML = `
      <div class="warning-message">
        <strong>Ready to import:</strong> ${rowCount} record(s) will be added to your database.
      </div>
    `;

    previewWarnings.innerHTML = '';

    if (parsedData.rows && parsedData.rows.length > 0) {
      renderDirectPreviewTable(parsedData.rows);
    } else {
      previewTableHead.innerHTML = '';
      previewTableBody.innerHTML = `
        <tr>
          <td colspan="10" style="text-align: center; padding: 2rem; color: #64748b;">
            File processed successfully. ${parsedData.imported || 0} record(s) ready to import.
          </td>
        </tr>
      `;
      markTableBodyRefreshed?.(previewTableBody);
    }
  } else {
    // Staged import preview
    const rows = parsedData.rows || [];

    previewStats.innerHTML = `
      <div class="warning-message">
        <strong>Found ${rows.length} transaction(s)</strong> • Review and edit before importing
      </div>
    `;

    renderStagedPreviewTable(rows);
  }
}

function renderDirectPreviewTable(rows) {
  if (!rows || rows.length === 0) return;

  const firstRow = rows[0];
  const columns = Object.keys(firstRow);

  // Render header
  previewTableHead.innerHTML = `
    <tr>
      ${columns.map(col => `<th>${escapeHtml(formatColumnName(col))}</th>`).join('')}
    </tr>
  `;

  // Render rows (limit to first 50 for performance)
  const displayRows = rows.slice(0, 50);
  previewTableBody.innerHTML = displayRows.map(row => `
    <tr>
      ${columns.map(col => {
        const value = row[col];
        const formatted = formatCellValue(col, value);
        return `<td>${escapeHtml(String(formatted))}</td>`;
      }).join('')}
    </tr>
  `).join('');

  if (rows.length > 50) {
    previewTableBody.innerHTML += `
      <tr>
        <td colspan="${columns.length}" style="text-align: center; padding: 1rem; color: #64748b;">
          ... and ${rows.length - 50} more record(s)
        </td>
      </tr>
    `;
  }

  markTableBodyRefreshed?.(previewTableBody);
}

function renderStagedPreviewTable(rows) {
  previewTableHead.innerHTML = `
    <tr>
      <th>Date</th>
      <th>Security</th>
      <th>Type</th>
      <th>Amount</th>
      <th>Shares</th>
      <th>Price/Share</th>
      <th>Commission</th>
    </tr>
  `;

  previewTableBody.innerHTML = rows.map((row, index) => `
    <tr>
      <td>${escapeHtml(row.trade_date || '')}</td>
      <td>${escapeHtml(row.security || '')}</td>
      <td>${escapeHtml(row.transaction_type || '')}</td>
      <td>${formatMoney(row.amount || 0)}</td>
      <td>${formatNumber(row.shares || 0, 6)}</td>
      <td>${formatMoney(row.amount_per_share || 0)}</td>
      <td>${formatMoney(row.commission || 0)}</td>
    </tr>
  `).join('');

  markTableBodyRefreshed?.(previewTableBody);
}

async function submitImport() {
  submitBtn.disabled = true;
  submitBtn.textContent = 'Importing...';

  try {
    const config = importTypeConfig[selectedImportType];

    if (config.direct) {
      // Direct import - data already imported during upload
      showCompletion(`Successfully imported ${parsedData.imported || parsedData.rows?.length || 0} record(s)`);
      goToStep(4);
    } else {
      // Staged import - commit the batch
      const result = await fetchJson(`/api/import/commit/${batchId}`, {
        method: 'POST'
      });

      showCompletion(`Successfully imported ${result.imported || 0} transaction(s)`);
      goToStep(4);
    }
  } catch (error) {
    showError(error.message || 'Failed to import data');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Import Data';
  }
}

function showCompletion(message) {
  completionMessage.textContent = message;
}

function showError(message) {
  uploadError.className = 'error-message';
  uploadError.textContent = message;
  setAnimatedVisibility(uploadError, true, 'block');
}

function clearFile() {
  uploadedFile = null;
  parsedData = null;
  batchId = null;
  fileInput.value = '';
  setAnimatedVisibility(dropzone, true, 'block');
  setAnimatedVisibility(fileInfo, false, 'block');
  setAnimatedVisibility(uploadError, false, 'block');
  nextBtn.style.display = 'none';
}

function resetWizard() {
  currentStep = 1;
  selectedImportType = null;
  uploadedFile = null;
  parsedData = null;
  batchId = null;
  fileInput.value = '';

  importTypeCards.forEach(card => card.classList.remove('selected'));
  setAnimatedVisibility(dropzone, true, 'block');
  setAnimatedVisibility(fileInfo, false, 'block');
  setAnimatedVisibility(uploadError, false, 'block');
}

// Utility functions
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatColumnName(name) {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatCellValue(columnName, value) {
  if (value === null || value === undefined) return '';

  const lowerCol = columnName.toLowerCase();

  if (lowerCol.includes('amount') || lowerCol.includes('value') || lowerCol.includes('price')) {
    return formatMoney(value);
  }

  if (lowerCol.includes('quantity') || lowerCol.includes('shares')) {
    return formatNumber(value, 6);
  }

  return value;
}

function formatMoney(value) {
  const num = Number(value);
  if (isNaN(num)) return value;
  return defaultCurrencyFormatter.format(num);
}

function formatNumber(value, decimals = 2) {
  const num = Number(value);
  if (isNaN(num)) return value;
  return num.toFixed(decimals);
}

// Initialize on load
document.addEventListener('DOMContentLoaded', init);
