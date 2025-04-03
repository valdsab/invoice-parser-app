/**
 * Main JavaScript file for the Invoice Parser application
 */

// Global variables to store application state
let currentInvoiceId = null;

// DOM elements
document.addEventListener('DOMContentLoaded', function() {
    // Initialize the application
    initApp();
});

/**
 * Initialize the application
 */
function initApp() {
    // Set up event listeners
    const invoiceUploadForm = document.getElementById('invoice-upload-form');
    if (invoiceUploadForm) {
        invoiceUploadForm.addEventListener('submit', handleInvoiceUpload);
    }
    
    const invoiceFileInput = document.getElementById('invoice-file');
    if (invoiceFileInput) {
        invoiceFileInput.addEventListener('change', function() {
            resetProcessingUI();
        });
    }
    
    const createVendorBillBtn = document.getElementById('create-vendor-bill-btn');
    if (createVendorBillBtn) {
        createVendorBillBtn.addEventListener('click', createVendorBill);
    }
    
    // Add checkbox event listeners for select all in invoice history
    const selectAllCheckbox = document.getElementById('select-all-invoices');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('.invoice-select');
            checkboxes.forEach(checkbox => {
                checkbox.checked = this.checked;
            });
            updateDeleteButtonState();
        });
    }
    
    // Load invoice history
    loadInvoiceHistory();
}

/**
 * Handle invoice upload form submission
 */
function handleInvoiceUpload(event) {
    event.preventDefault();
    
    const invoiceFileInput = document.getElementById('invoice-file');
    const uploadBtn = document.getElementById('upload-btn');
    const processingSteps = document.getElementById('processing-steps');
    const stepUpload = document.getElementById('step-upload');
    const stepParse = document.getElementById('step-parse');
    
    // Validate file selection
    const file = invoiceFileInput.files[0];
    if (!file) {
        showStatus('error', 'Please select a file to upload.');
        return;
    }
    
    // Check file type
    const fileType = file.type;
    if (!['application/pdf', 'image/jpeg', 'image/png'].includes(fileType)) {
        showStatus('error', 'Invalid file type. Please upload a PDF, JPG, or PNG file.');
        return;
    }
    
    // Check file size (max 16MB)
    if (file.size > 16 * 1024 * 1024) {
        showStatus('error', 'File size exceeds the limit of 16MB.');
        return;
    }
    
    // Reset UI and show processing steps
    resetProcessingUI();
    if (processingSteps) {
        processingSteps.classList.remove('d-none');
    }
    updateStepStatus(stepUpload, 'processing');
    
    // Create form data
    const formData = new FormData();
    formData.append('invoice', file);
    
    // Disable upload button
    if (uploadBtn) {
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Uploading...';
    }
    
    // Upload file
    showStatus('info', 'Uploading invoice file...');
    
    // Keep track of client-side timeout
    let processingTimeout;
    let pollingInterval;
    let uploadedInvoiceId = null;
    
    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Upload successful, but we might need to poll if still processing
            updateStepStatus(stepUpload, 'complete');
            
            // Store current invoice ID
            currentInvoiceId = data.invoice_id;
            uploadedInvoiceId = data.invoice_id;
            
            // If the invoice is already parsed, display it immediately
            if (data.invoice_data && data.invoice_data.status === 'parsed') {
                updateStepStatus(stepParse, 'complete');
                showStatus('success', 'Invoice uploaded and parsed successfully!');
                displayInvoiceDetails(data.invoice_data);
                loadInvoiceHistory();
            } else {
                // Otherwise, start polling for status updates
                updateStepStatus(stepParse, 'processing');
                showStatus('info', 'Invoice uploaded. Processing document...');
                
                // Poll for invoice status updates
                let pollCount = 0;
                const maxPolls = 20; // Maximum number of polling attempts
                
                // Set a 60-second client-side timeout for processing
                processingTimeout = setTimeout(() => {
                    // Stop polling
                    if (pollingInterval) {
                        clearInterval(pollingInterval);
                    }
                    
                    // Update UI to show timeout
                    updateStepStatus(stepParse, 'error');
                    showStatus('error', 'Invoice processing timed out. Please check the invoice history for status updates.');
                    loadInvoiceHistory();
                }, 60000); // 60 seconds timeout
                
                // Poll every 3 seconds
                pollingInterval = setInterval(() => {
                    pollCount++;
                    
                    // Get invoice status
                    fetch(`/invoices/${uploadedInvoiceId}`)
                        .then(response => response.json())
                        .then(invoiceData => {
                            const status = invoiceData.invoice.status;
                            
                            // Update UI based on status
                            if (status === 'parsed' || status === 'completed') {
                                // Stop polling and timeout
                                clearInterval(pollingInterval);
                                clearTimeout(processingTimeout);
                                
                                // Update UI
                                updateStepStatus(stepParse, 'complete');
                                showStatus('success', 'Invoice parsed successfully!');
                                displayInvoiceDetails(invoiceData.invoice);
                                loadInvoiceHistory();
                            } else if (status === 'error') {
                                // Stop polling and timeout
                                clearInterval(pollingInterval);
                                clearTimeout(processingTimeout);
                                
                                // Update UI
                                updateStepStatus(stepParse, 'error');
                                showStatus('error', `Error parsing invoice: ${invoiceData.invoice.error_message || 'Unknown error'}`);
                                loadInvoiceHistory();
                            } else if (pollCount >= maxPolls) {
                                // Stop polling if max attempts reached
                                clearInterval(pollingInterval);
                                clearTimeout(processingTimeout);
                                
                                // Update UI
                                updateStepStatus(stepParse, 'error');
                                showStatus('error', 'Invoice processing took too long. Please check the invoice history for status updates.');
                                loadInvoiceHistory();
                            }
                        })
                        .catch(error => {
                            console.error('Error polling invoice status:', error);
                            // Continue polling despite errors, timeout will eventually stop it if needed
                        });
                }, 3000); // Poll every 3 seconds
            }
        } else {
            // Upload failed
            updateStepStatus(stepUpload, 'complete');
            updateStepStatus(stepParse, 'error');
            showStatus('error', `Error parsing invoice: ${data.error}`);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        updateStepStatus(stepUpload, 'error');
        showStatus('error', `An error occurred: ${error.message}`);
    })
    .finally(() => {
        // Re-enable upload button
        if (uploadBtn) {
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = '<i class="fas fa-upload me-2"></i>Upload & Parse';
        }
    });
}

/**
 * Display invoice details in the UI
 */
function displayInvoiceDetails(invoiceData) {
    const invoiceDetailsContainer = document.getElementById('invoice-details-container');
    const vendorNameElement = document.getElementById('vendor-name');
    const invoiceNumberElement = document.getElementById('invoice-number');
    const invoiceDateElement = document.getElementById('invoice-date');
    const dueDateElement = document.getElementById('due-date');
    const totalAmountElement = document.getElementById('total-amount');
    const parserUsedElement = document.getElementById('parser-used');
    const lineItemsTable = document.getElementById('line-items-table').querySelector('tbody');
    
    // Show the invoice details container
    if (invoiceDetailsContainer) {
        invoiceDetailsContainer.classList.remove('d-none');
    }
    
    // Populate invoice details
    if (vendorNameElement) vendorNameElement.textContent = invoiceData.vendor_name || 'N/A';
    if (invoiceNumberElement) invoiceNumberElement.textContent = invoiceData.invoice_number || 'N/A';
    if (invoiceDateElement) invoiceDateElement.textContent = formatDate(invoiceData.invoice_date) || 'N/A';
    if (dueDateElement) dueDateElement.textContent = formatDate(invoiceData.due_date) || 'N/A';
    if (totalAmountElement) totalAmountElement.textContent = formatCurrency(invoiceData.total_amount) || 'N/A';
    
    // Clear existing line items
    if (lineItemsTable) {
        lineItemsTable.innerHTML = '';
        
        // Load line items and raw OCR data
        fetch(`/invoices/${invoiceData.id}`)
            .then(response => response.json())
            .then(data => {
                // Display which parser was used
                if (parserUsedElement) {
                    parserUsedElement.textContent = data.parser_used || 'Unknown';
                    
                    // Add a visual indicator of which parser was used
                    if (data.parser_used === 'LlamaCloud') {
                        parserUsedElement.innerHTML = 'LlamaCloud <span class="badge bg-primary">Primary</span>';
                    } else if (data.parser_used === 'Eyelevel') {
                        parserUsedElement.innerHTML = 'Eyelevel <span class="badge bg-secondary">Fallback</span>';
                    }
                }
                
                // Populate line items table
                const lineItems = data.line_items;
                if (lineItems && lineItems.length > 0) {
                    lineItems.forEach(item => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${item.description || 'N/A'}</td>
                            <td>${item.project_number || 'N/A'}</td>
                            <td>${item.project_name || 'N/A'}</td>
                            <td>${item.activity_code || 'N/A'}</td>
                            <td>${item.quantity || '1'}</td>
                            <td>${formatCurrency(item.unit_price) || 'N/A'}</td>
                            <td>${formatCurrency(item.amount) || 'N/A'}</td>
                            <td>${formatCurrency(item.tax) || '0.00'}</td>
                        `;
                        lineItemsTable.appendChild(row);
                    });
                } else {
                    // No line items
                    const row = document.createElement('tr');
                    row.innerHTML = '<td colspan="8" class="text-center">No line items found</td>';
                    lineItemsTable.appendChild(row);
                }
                
                // Add raw OCR data section if available
                if (data.invoice.parsed_data) {
                    try {
                        // Check if we have raw data from either LlamaCloud or Eyelevel
                        let rawData = null;
                        let dataSourceName = '';
                        
                        if (data.raw_extraction_data) {
                            // LlamaCloud data
                            rawData = data.raw_extraction_data;
                            dataSourceName = 'LlamaCloud';
                        } else if (data.raw_xray_data) {
                            // Eyelevel data
                            rawData = data.raw_xray_data;
                            dataSourceName = 'Eyelevel.ai';
                        }
                        
                        if (rawData) {
                            // Create raw data section if not exists
                            let rawDataSection = document.getElementById('raw-ocr-data-section');
                            if (!rawDataSection) {
                                const parent = document.querySelector('#invoice-details-container .card-body');
                                
                                rawDataSection = document.createElement('div');
                                rawDataSection.id = 'raw-ocr-data-section';
                                rawDataSection.className = 'mt-4';
                                
                                const heading = document.createElement('h4');
                                heading.id = 'raw-data-heading';
                                heading.textContent = `Raw OCR Data (${dataSourceName})`;
                                rawDataSection.appendChild(heading);
                                
                                const toggleBtn = document.createElement('button');
                                toggleBtn.className = 'btn btn-sm btn-info mb-2';
                                toggleBtn.textContent = 'Show Raw Data';
                                toggleBtn.onclick = function() {
                                    const pre = document.getElementById('raw-ocr-json');
                                    if (pre.classList.contains('d-none')) {
                                        pre.classList.remove('d-none');
                                        this.textContent = 'Hide Raw Data';
                                    } else {
                                        pre.classList.add('d-none');
                                        this.textContent = 'Show Raw Data';
                                    }
                                };
                                rawDataSection.appendChild(toggleBtn);
                                
                                const pre = document.createElement('pre');
                                pre.id = 'raw-ocr-json';
                                pre.className = 'd-none bg-dark text-light p-3 rounded';
                                pre.style.maxHeight = '500px';
                                pre.style.overflow = 'auto';
                                rawDataSection.appendChild(pre);
                                
                                parent.appendChild(rawDataSection);
                            } else {
                                // Update the heading to show correct data source
                                const heading = document.getElementById('raw-data-heading');
                                if (heading) {
                                    heading.textContent = `Raw OCR Data (${dataSourceName})`;
                                }
                            }
                            
                            // Update raw data content
                            const pre = document.getElementById('raw-ocr-json');
                            if (pre) {
                                pre.textContent = JSON.stringify(rawData, null, 2);
                            }
                        }
                    } catch (e) {
                        console.error('Error parsing OCR data:', e);
                    }
                }
            })
            .catch(error => {
                console.error('Error fetching line items:', error);
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="8" class="text-center text-danger">Error loading line items</td>';
                lineItemsTable.appendChild(row);
            });
    }
}

/**
 * Create vendor bill in Zoho Books
 */
function createVendorBill() {
    const createVendorBillBtn = document.getElementById('create-vendor-bill-btn');
    const stepCreate = document.getElementById('step-create');
    
    // Validate current invoice ID
    if (!currentInvoiceId) {
        showVendorBillStatus('error', 'No invoice selected.');
        return;
    }
    
    // Show processing UI
    updateStepStatus(stepCreate, 'processing');
    if (createVendorBillBtn) {
        createVendorBillBtn.disabled = true;
        createVendorBillBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Creating Vendor Bill...';
    }
    showVendorBillStatus('info', 'Creating vendor bill in Zoho Books...');
    
    // Send request to create vendor bill
    fetch(`/create_vendor_bill/${currentInvoiceId}`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Vendor bill created successfully
            updateStepStatus(stepCreate, 'complete');
            showVendorBillStatus('success', `Vendor bill created successfully! ID: ${data.vendor_bill_id}`);
            
            // Refresh invoice history
            loadInvoiceHistory();
        } else {
            // Error creating vendor bill
            updateStepStatus(stepCreate, 'error');
            showVendorBillStatus('error', `Error creating vendor bill: ${data.error}`);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        updateStepStatus(stepCreate, 'error');
        showVendorBillStatus('error', `An error occurred: ${error.message}`);
    })
    .finally(() => {
        // Re-enable create button
        if (createVendorBillBtn) {
            createVendorBillBtn.disabled = false;
            createVendorBillBtn.innerHTML = '<i class="fas fa-file-invoice-dollar me-2"></i>Create Vendor Bill in Zoho Books';
        }
    });
}

/**
 * Load invoice history
 */
function loadInvoiceHistory() {
    const invoiceHistoryTable = document.getElementById('invoice-history-table')?.querySelector('tbody');
    const noInvoicesMessage = document.getElementById('no-invoices-message');
    
    if (!invoiceHistoryTable) return;
    
    fetch('/invoices')
        .then(response => response.json())
        .then(data => {
            // Clear existing table rows
            invoiceHistoryTable.innerHTML = '';
            
            const invoices = data.invoices;
            if (invoices && invoices.length > 0) {
                // Hide no invoices message
                if (noInvoicesMessage) {
                    noInvoicesMessage.classList.add('d-none');
                }
                
                // Show delete selected button
                if (!document.getElementById('delete-selected-btn')) {
                    // Create delete selected button
                    const deleteBtn = document.createElement('button');
                    deleteBtn.id = 'delete-selected-btn';
                    deleteBtn.className = 'btn btn-danger mb-3';
                    deleteBtn.innerHTML = '<i class="fas fa-trash-alt me-2"></i>Delete Selected';
                    deleteBtn.disabled = true;
                    deleteBtn.addEventListener('click', deleteSelectedInvoices);
                    
                    // Create select all checkbox
                    const selectAllContainer = document.createElement('div');
                    selectAllContainer.className = 'd-flex justify-content-between align-items-center mb-2';
                    
                    const selectAllLabel = document.createElement('label');
                    selectAllLabel.className = 'form-check form-check-inline mb-0';
                    selectAllLabel.innerHTML = `
                        <input class="form-check-input" type="checkbox" id="select-all-invoices">
                        <span class="form-check-label">Select All</span>
                    `;
                    
                    selectAllContainer.appendChild(selectAllLabel);
                    selectAllContainer.appendChild(deleteBtn);
                    
                    // Insert before the table
                    const tableContainer = document.querySelector('#invoice-history .table-responsive');
                    if (tableContainer) {
                        tableContainer.parentNode.insertBefore(selectAllContainer, tableContainer);
                    }
                    
                    // Add event listener to select all checkbox
                    document.getElementById('select-all-invoices')?.addEventListener('change', function() {
                        const checkboxes = document.querySelectorAll('.invoice-select');
                        checkboxes.forEach(checkbox => {
                            checkbox.checked = this.checked;
                        });
                        updateDeleteButtonState();
                    });
                }
                
                // Add table header with checkbox column
                const headerRow = document.createElement('tr');
                headerRow.innerHTML = `
                    <th><div class="form-check"></div></th>
                    <th>ID</th>
                    <th>File Name</th>
                    <th>Vendor</th>
                    <th>Invoice #</th>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Actions</th>
                `;
                invoiceHistoryTable.appendChild(headerRow);
                
                // Add each invoice to the table
                invoices.forEach(invoice => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>
                            <div class="form-check">
                                <input class="form-check-input invoice-select" type="checkbox" data-invoice-id="${invoice.id}">
                            </div>
                        </td>
                        <td>${invoice.id}</td>
                        <td>${invoice.file_name || 'N/A'}</td>
                        <td>${invoice.vendor_name || 'N/A'}</td>
                        <td>${invoice.invoice_number || 'N/A'}</td>
                        <td>${formatDate(invoice.invoice_date) || 'N/A'}</td>
                        <td>${formatCurrency(invoice.total_amount) || 'N/A'}</td>
                        <td>${formatStatus(invoice.status)}</td>
                        <td>
                            <div class="btn-group btn-group-sm" role="group">
                                <button type="button" class="btn btn-primary view-invoice" title="View Details" 
                                        onclick="viewInvoice(${invoice.id})">
                                    <i class="fas fa-eye"></i>
                                </button>
                                <button type="button" class="btn btn-danger delete-invoice" title="Delete" 
                                        onclick="deleteInvoice(${invoice.id})">
                                    <i class="fas fa-trash-alt"></i>
                                </button>
                            </div>
                        </td>
                    `;
                    invoiceHistoryTable.appendChild(row);
                });
                
                // Add checkbox event listeners
                document.querySelectorAll('.invoice-select').forEach(checkbox => {
                    checkbox.addEventListener('change', updateDeleteButtonState);
                });
            } else {
                // No invoices found
                if (noInvoicesMessage) {
                    noInvoicesMessage.classList.remove('d-none');
                }
                
                // Remove delete selected button if exists
                const deleteSelectedBtn = document.getElementById('delete-selected-btn');
                if (deleteSelectedBtn) {
                    deleteSelectedBtn.parentNode.remove();
                }
            }
        })
        .catch(error => {
            console.error('Error loading invoice history:', error);
            invoiceHistoryTable.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center text-danger">
                        <i class="fas fa-exclamation-circle me-2"></i>
                        Error loading invoice history
                    </td>
                </tr>
            `;
        });
}

/**
 * Update delete button state based on checkbox selection
 */
function updateDeleteButtonState() {
    const deleteBtn = document.getElementById('delete-selected-btn');
    const checkedBoxes = document.querySelectorAll('.invoice-select:checked');
    
    if (deleteBtn) {
        deleteBtn.disabled = checkedBoxes.length === 0;
    }
}

/**
 * Delete a single invoice
 */
function deleteInvoice(invoiceId) {
    if (confirm(`Are you sure you want to delete invoice #${invoiceId}? This action cannot be undone.`)) {
        fetch(`/invoices/${invoiceId}`, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showStatus('success', `Invoice #${invoiceId} deleted successfully.`);
                
                // Clear current invoice if it's the one we just deleted
                if (currentInvoiceId === invoiceId) {
                    resetProcessingUI();
                    const invoiceDetailsContainer = document.getElementById('invoice-details-container');
                    if (invoiceDetailsContainer) {
                        invoiceDetailsContainer.classList.add('d-none');
                    }
                    currentInvoiceId = null;
                }
                
                // Refresh invoice history
                loadInvoiceHistory();
            } else {
                showStatus('error', `Error deleting invoice: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showStatus('error', `An error occurred while deleting the invoice: ${error.message}`);
        });
    }
}

/**
 * Delete multiple selected invoices
 */
function deleteSelectedInvoices() {
    const checkedBoxes = document.querySelectorAll('.invoice-select:checked');
    const invoiceIds = Array.from(checkedBoxes).map(checkbox => 
        parseInt(checkbox.getAttribute('data-invoice-id'))
    );
    
    if (invoiceIds.length === 0) {
        showStatus('error', 'No invoices selected.');
        return;
    }
    
    if (confirm(`Are you sure you want to delete ${invoiceIds.length} invoice(s)? This action cannot be undone.`)) {
        fetch('/delete_invoices', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ invoice_ids: invoiceIds }),
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showStatus('success', `${data.deleted_count} invoice(s) deleted successfully.`);
                
                // Clear current invoice if it was deleted
                if (currentInvoiceId && invoiceIds.includes(parseInt(currentInvoiceId))) {
                    resetProcessingUI();
                    const invoiceDetailsContainer = document.getElementById('invoice-details-container');
                    if (invoiceDetailsContainer) {
                        invoiceDetailsContainer.classList.add('d-none');
                    }
                    currentInvoiceId = null;
                }
                
                // Refresh invoice history
                loadInvoiceHistory();
            } else {
                showStatus('error', `Error deleting invoices: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showStatus('error', `An error occurred while deleting invoices: ${error.message}`);
        });
    }
}

/**
 * View invoice details
 */
function viewInvoice(invoiceId) {
    fetch(`/invoices/${invoiceId}`)
        .then(response => response.json())
        .then(data => {
            // Set current invoice ID
            currentInvoiceId = invoiceId;
            
            // Display invoice details
            displayInvoiceDetails(data.invoice);
            
            // Update processing steps based on invoice status
            updateStepsFromInvoiceStatus(data.invoice.status);
            
            // Scroll to details
            const invoiceDetailsContainer = document.getElementById('invoice-details-container');
            if (invoiceDetailsContainer) {
                invoiceDetailsContainer.scrollIntoView({ behavior: 'smooth' });
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showStatus('error', `Error fetching invoice details: ${error.message}`);
        });
}

/**
 * Update processing step status based on invoice status
 */
function updateStepsFromInvoiceStatus(status) {
    const processingSteps = document.getElementById('processing-steps');
    const stepUpload = document.getElementById('step-upload');
    const stepParse = document.getElementById('step-parse');
    const stepCreate = document.getElementById('step-create');
    
    if (processingSteps) {
        processingSteps.classList.remove('d-none');
    }
    
    // Always mark upload as complete
    updateStepStatus(stepUpload, 'complete');
    
    // Mark parse step based on status
    if (status === 'uploaded' || status === 'processing') {
        updateStepStatus(stepParse, 'processing');
    } else if (status === 'parsed' || status === 'completed') {
        updateStepStatus(stepParse, 'complete');
    } else if (status === 'error') {
        updateStepStatus(stepParse, 'error');
    }
    
    // Mark create step based on status
    if (status === 'completed') {
        updateStepStatus(stepCreate, 'complete');
    } else {
        updateStepStatus(stepCreate, 'waiting');
    }
}

/**
 * Show status message
 */
function showStatus(type, message) {
    const uploadStatus = document.getElementById('upload-status');
    if (!uploadStatus) return;
    
    let icon = '';
    switch(type) {
        case 'success':
            icon = '<i class="fas fa-check-circle me-2"></i>';
            break;
        case 'error':
            icon = '<i class="fas fa-exclamation-circle me-2"></i>';
            break;
        case 'warning':
            icon = '<i class="fas fa-exclamation-triangle me-2"></i>';
            break;
        case 'info':
        default:
            icon = '<i class="fas fa-info-circle me-2"></i>';
            break;
    }
    
    uploadStatus.innerHTML = `
        <div class="alert alert-${type}">
            ${icon}${message}
        </div>
    `;
}

/**
 * Show vendor bill status message
 */
function showVendorBillStatus(type, message) {
    const vendorBillStatus = document.getElementById('vendor-bill-status');
    if (!vendorBillStatus) return;
    
    let icon = '';
    switch(type) {
        case 'success':
            icon = '<i class="fas fa-check-circle me-2"></i>';
            break;
        case 'error':
            icon = '<i class="fas fa-exclamation-circle me-2"></i>';
            break;
        case 'warning':
            icon = '<i class="fas fa-exclamation-triangle me-2"></i>';
            break;
        case 'info':
        default:
            icon = '<i class="fas fa-info-circle me-2"></i>';
            break;
    }
    
    vendorBillStatus.innerHTML = `
        <div class="alert alert-${type}">
            ${icon}${message}
        </div>
    `;
}

/**
 * Update processing step status
 */
function updateStepStatus(element, status) {
    if (!element) return;
    
    // Remove all status classes
    element.classList.remove('step-processing', 'step-complete', 'step-error', 'step-waiting');
    
    // Add appropriate status class
    element.classList.add(`step-${status}`);
    
    // Update icon
    const icon = element.querySelector('.step-icon');
    if (!icon) return;
    
    // Remove all icons
    icon.classList.remove('fa-circle', 'fa-spinner', 'fa-check-circle', 'fa-times-circle');
    
    // Add appropriate icon
    switch(status) {
        case 'processing':
            icon.classList.add('fa-spinner', 'fa-spin');
            break;
        case 'complete':
            icon.classList.add('fa-check-circle');
            break;
        case 'error':
            icon.classList.add('fa-times-circle');
            break;
        case 'waiting':
        default:
            icon.classList.add('fa-circle');
            break;
    }
}

/**
 * Reset processing UI elements
 */
function resetProcessingUI() {
    const processingSteps = document.getElementById('processing-steps');
    const stepUpload = document.getElementById('step-upload');
    const stepParse = document.getElementById('step-parse');
    const stepCreate = document.getElementById('step-create');
    
    if (processingSteps) {
        processingSteps.classList.add('d-none');
    }
    
    updateStepStatus(stepUpload, 'waiting');
    updateStepStatus(stepParse, 'waiting');
    updateStepStatus(stepCreate, 'waiting');
}

/**
 * Format date string
 */
function formatDate(dateString) {
    if (!dateString) return null;
    
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return dateString; // Return original if invalid
    
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

/**
 * Format currency value
 */
function formatCurrency(value) {
    if (value === null || value === undefined) return null;
    
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(value);
}

/**
 * Format invoice status
 */
function formatStatus(status) {
    if (!status) return '<span class="badge bg-secondary">Unknown</span>';
    
    let badgeClass = 'bg-secondary';
    let icon = 'fa-question-circle';
    
    switch(status.toLowerCase()) {
        case 'uploaded':
            badgeClass = 'bg-primary';
            icon = 'fa-upload';
            break;
        case 'processing':
            badgeClass = 'bg-info';
            icon = 'fa-spinner fa-spin';
            break;
        case 'parsed':
            badgeClass = 'bg-success';
            icon = 'fa-check-circle';
            break;
        case 'completed':
            badgeClass = 'bg-dark';
            icon = 'fa-file-invoice-dollar';
            break;
        case 'error':
            badgeClass = 'bg-danger';
            icon = 'fa-exclamation-circle';
            break;
    }
    
    return `<span class="badge ${badgeClass}"><i class="fas ${icon} me-1"></i>${status}</span>`;
}

// Custom CSS for processing steps
document.addEventListener('DOMContentLoaded', function() {
    const style = document.createElement('style');
    style.textContent = `
        .step-waiting .step-icon { color: #6c757d; }
        .step-processing .step-icon { color: #17a2b8; }
        .step-complete .step-icon { color: #28a745; }
        .step-error .step-icon { color: #dc3545; }
    `;
    document.head.appendChild(style);
});