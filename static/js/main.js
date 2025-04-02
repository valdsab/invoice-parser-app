/**
 * Main JavaScript file for the Invoice Parser application
 */
document.addEventListener('DOMContentLoaded', function() {
    // Store the current invoice ID being processed
    let currentInvoiceId = null;
    
    // DOM Elements
    const invoiceUploadForm = document.getElementById('invoice-upload-form');
    const invoiceFileInput = document.getElementById('invoice-file');
    const uploadBtn = document.getElementById('upload-btn');
    const uploadStatus = document.getElementById('upload-status');
    const processingSteps = document.getElementById('processing-steps');
    const stepUpload = document.getElementById('step-upload');
    const stepParse = document.getElementById('step-parse');
    const stepCreate = document.getElementById('step-create');
    const invoiceDetailsContainer = document.getElementById('invoice-details-container');
    const vendorNameElement = document.getElementById('vendor-name');
    const invoiceNumberElement = document.getElementById('invoice-number');
    const invoiceDateElement = document.getElementById('invoice-date');
    const dueDateElement = document.getElementById('due-date');
    const totalAmountElement = document.getElementById('total-amount');
    const lineItemsTable = document.getElementById('line-items-table').querySelector('tbody');
    const createVendorBillBtn = document.getElementById('create-vendor-bill-btn');
    const vendorBillStatus = document.getElementById('vendor-bill-status');
    const invoiceHistoryTable = document.getElementById('invoice-history-table').querySelector('tbody');
    const noInvoicesMessage = document.getElementById('no-invoices-message');
    
    // Initialize the application
    init();
    
    /**
     * Initialize the application
     */
    function init() {
        // Load invoice history
        loadInvoiceHistory();
        
        // Set up event listeners
        invoiceUploadForm.addEventListener('submit', handleInvoiceUpload);
        createVendorBillBtn.addEventListener('click', createVendorBill);
        
        // Reset form when file input changes
        invoiceFileInput.addEventListener('change', function() {
            resetProcessingUI();
        });
    }
    
    /**
     * Handle invoice upload form submission
     */
    function handleInvoiceUpload(event) {
        event.preventDefault();
        
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
        processingSteps.classList.remove('d-none');
        updateStepStatus(stepUpload, 'processing');
        
        // Create form data
        const formData = new FormData();
        formData.append('invoice', file);
        
        // Disable upload button
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Uploading...';
        
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
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = '<i class="fas fa-upload me-2"></i>Upload & Parse';
        });
    }
    
    /**
     * Display invoice details in the UI
     */
    function displayInvoiceDetails(invoiceData) {
        // Show the invoice details container
        invoiceDetailsContainer.classList.remove('d-none');
        
        // Populate invoice details
        vendorNameElement.textContent = invoiceData.vendor_name || 'N/A';
        invoiceNumberElement.textContent = invoiceData.invoice_number || 'N/A';
        invoiceDateElement.textContent = formatDate(invoiceData.invoice_date) || 'N/A';
        dueDateElement.textContent = formatDate(invoiceData.due_date) || 'N/A';
        totalAmountElement.textContent = formatCurrency(invoiceData.total_amount) || 'N/A';
        
        // Clear existing line items
        lineItemsTable.innerHTML = '';
        
        // Load line items and raw OCR data
        fetch(`/invoices/${invoiceData.id}`)
            .then(response => response.json())
            .then(data => {
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
                        const parsedData = JSON.parse(data.invoice.parsed_data);
                        if (parsedData.raw_response) {
                            // Create raw data section if not exists
                            let rawDataSection = document.getElementById('raw-ocr-data-section');
                            if (!rawDataSection) {
                                const parent = document.querySelector('#invoice-details-container .card-body');
                                
                                rawDataSection = document.createElement('div');
                                rawDataSection.id = 'raw-ocr-data-section';
                                rawDataSection.className = 'mt-4';
                                
                                const heading = document.createElement('h4');
                                heading.textContent = 'Raw OCR Data (Eyelevel.ai)';
                                rawDataSection.appendChild(heading);
                                
                                const toggleBtn = document.createElement('button');
                                toggleBtn.className = 'btn btn-sm btn-info mb-2';
                                toggleBtn.textContent = 'Show/Hide Raw Data';
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
                            }
                            
                            // Update raw data content
                            const pre = document.getElementById('raw-ocr-json');
                            pre.textContent = JSON.stringify(parsedData.raw_response, null, 2);
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
    
    /**
     * Create vendor bill in Zoho Books
     */
    function createVendorBill() {
        // Validate current invoice ID
        if (!currentInvoiceId) {
            showVendorBillStatus('error', 'No invoice selected.');
            return;
        }
        
        // Show processing UI
        updateStepStatus(stepCreate, 'processing');
        createVendorBillBtn.disabled = true;
        createVendorBillBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Creating Vendor Bill...';
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
            createVendorBillBtn.disabled = false;
            createVendorBillBtn.innerHTML = '<i class="fas fa-file-invoice-dollar me-2"></i>Create Vendor Bill in Zoho Books';
        });
    }
    
    /**
     * Load invoice history
     */
    function loadInvoiceHistory() {
        fetch('/invoices')
            .then(response => response.json())
            .then(data => {
                // Clear existing table rows
                invoiceHistoryTable.innerHTML = '';
                
                const invoices = data.invoices;
                if (invoices && invoices.length > 0) {
                    // Hide no invoices message
                    noInvoicesMessage.classList.add('d-none');
                    
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
                        tableContainer.parentNode.insertBefore(selectAllContainer, tableContainer);
                        
                        // Add event listener to select all checkbox
                        document.getElementById('select-all-invoices').addEventListener('change', function() {
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
                            <td>${invoice.file_name}</td>
                            <td>${invoice.vendor_name || 'N/A'}</td>
                            <td>${invoice.invoice_number || 'N/A'}</td>
                            <td>${formatDate(invoice.invoice_date)}</td>
                            <td>${formatCurrency(invoice.total_amount)}</td>
                            <td>${formatStatus(invoice.status)}</td>
                            <td>
                                <button class="btn btn-sm btn-primary view-invoice-btn" data-invoice-id="${invoice.id}" title="View Details">
                                    <i class="fas fa-eye"></i>
                                </button>
                                ${invoice.status === 'parsed' ? `
                                <button class="btn btn-sm btn-success create-bill-btn" data-invoice-id="${invoice.id}" title="Create Vendor Bill">
                                    <i class="fas fa-file-invoice-dollar"></i>
                                </button>
                                ` : ''}
                                <button class="btn btn-sm btn-danger delete-invoice-btn" data-invoice-id="${invoice.id}" title="Delete">
                                    <i class="fas fa-trash-alt"></i>
                                </button>
                            </td>
                        `;
                        invoiceHistoryTable.appendChild(row);
                    });
                    
                    // Add event listeners to action buttons
                    document.querySelectorAll('.view-invoice-btn').forEach(btn => {
                        btn.addEventListener('click', function() {
                            const invoiceId = this.getAttribute('data-invoice-id');
                            viewInvoice(invoiceId);
                        });
                    });
                    
                    document.querySelectorAll('.create-bill-btn').forEach(btn => {
                        btn.addEventListener('click', function() {
                            const invoiceId = this.getAttribute('data-invoice-id');
                            currentInvoiceId = invoiceId;
                            createVendorBill();
                        });
                    });
                    
                    document.querySelectorAll('.delete-invoice-btn').forEach(btn => {
                        btn.addEventListener('click', function() {
                            const invoiceId = this.getAttribute('data-invoice-id');
                            deleteInvoice(invoiceId);
                        });
                    });
                    
                    // Add event listeners to checkboxes
                    document.querySelectorAll('.invoice-select').forEach(checkbox => {
                        checkbox.addEventListener('change', updateDeleteButtonState);
                    });
                } else {
                    // Show no invoices message
                    noInvoicesMessage.classList.remove('d-none');
                    
                    // Remove delete selected button if it exists
                    const deleteBtn = document.getElementById('delete-selected-btn');
                    const selectAllContainer = deleteBtn?.parentNode;
                    if (selectAllContainer) {
                        selectAllContainer.remove();
                    }
                }
            })
            .catch(error => {
                console.error('Error loading invoice history:', error);
                invoiceHistoryTable.innerHTML = `
                    <tr>
                        <td colspan="9" class="text-center text-danger">
                            Error loading invoice history: ${error.message}
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
        if (deleteBtn) {
            const checkedBoxes = document.querySelectorAll('.invoice-select:checked');
            deleteBtn.disabled = checkedBoxes.length === 0;
            
            // Update select all checkbox
            const selectAllCheckbox = document.getElementById('select-all-invoices');
            const allCheckboxes = document.querySelectorAll('.invoice-select');
            if (selectAllCheckbox && allCheckboxes.length > 0) {
                selectAllCheckbox.checked = checkedBoxes.length === allCheckboxes.length;
                selectAllCheckbox.indeterminate = checkedBoxes.length > 0 && checkedBoxes.length < allCheckboxes.length;
            }
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
                    showStatus('success', data.message);
                    
                    // Reload invoice history
                    loadInvoiceHistory();
                    
                    // If the deleted invoice is the current one, reset the UI
                    if (currentInvoiceId === invoiceId) {
                        resetProcessingUI();
                        invoiceDetailsContainer.classList.add('d-none');
                        currentInvoiceId = null;
                    }
                } else {
                    showStatus('error', data.message);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showStatus('error', `An error occurred: ${error.message}`);
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
            return;
        }
        
        if (confirm(`Are you sure you want to delete ${invoiceIds.length} selected invoice(s)? This action cannot be undone.`)) {
            fetch('/invoices/delete-multiple', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ invoice_ids: invoiceIds })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showStatus('success', data.message);
                    
                    // Reload invoice history
                    loadInvoiceHistory();
                    
                    // If the current invoice is among the deleted ones, reset the UI
                    if (currentInvoiceId && invoiceIds.includes(parseInt(currentInvoiceId))) {
                        resetProcessingUI();
                        invoiceDetailsContainer.classList.add('d-none');
                        currentInvoiceId = null;
                    }
                } else {
                    showStatus('error', data.message);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showStatus('error', `An error occurred: ${error.message}`);
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
                
                // Scroll to invoice details
                invoiceDetailsContainer.scrollIntoView({ behavior: 'smooth' });
                
                // Update step status based on invoice status
                updateStepsFromInvoiceStatus(data.invoice.status);
            })
            .catch(error => {
                console.error('Error viewing invoice:', error);
                showStatus('error', `Error loading invoice details: ${error.message}`);
            });
    }
    
    /**
     * Update processing step status based on invoice status
     */
    function updateStepsFromInvoiceStatus(status) {
        processingSteps.classList.remove('d-none');
        
        switch (status) {
            case 'uploaded':
                updateStepStatus(stepUpload, 'complete');
                updateStepStatus(stepParse, 'pending');
                updateStepStatus(stepCreate, 'pending');
                break;
            case 'processing':
                updateStepStatus(stepUpload, 'complete');
                updateStepStatus(stepParse, 'processing');
                updateStepStatus(stepCreate, 'pending');
                break;
            case 'parsed':
                updateStepStatus(stepUpload, 'complete');
                updateStepStatus(stepParse, 'complete');
                updateStepStatus(stepCreate, 'pending');
                break;
            case 'completed':
                updateStepStatus(stepUpload, 'complete');
                updateStepStatus(stepParse, 'complete');
                updateStepStatus(stepCreate, 'complete');
                break;
            case 'error':
                // Determine which step had the error
                if (invoiceDetailsContainer.classList.contains('d-none')) {
                    // Error during parsing
                    updateStepStatus(stepUpload, 'complete');
                    updateStepStatus(stepParse, 'error');
                    updateStepStatus(stepCreate, 'pending');
                } else {
                    // Error during vendor bill creation
                    updateStepStatus(stepUpload, 'complete');
                    updateStepStatus(stepParse, 'complete');
                    updateStepStatus(stepCreate, 'error');
                }
                break;
        }
    }
    
    /**
     * Show status message
     */
    function showStatus(type, message) {
        let icon, className;
        
        switch (type) {
            case 'success':
                icon = 'fas fa-check-circle';
                className = 'alert-success';
                break;
            case 'error':
                icon = 'fas fa-exclamation-circle';
                className = 'alert-danger';
                break;
            case 'warning':
                icon = 'fas fa-exclamation-triangle';
                className = 'alert-warning';
                break;
            case 'info':
            default:
                icon = 'fas fa-info-circle';
                className = 'alert-info';
                break;
        }
        
        uploadStatus.innerHTML = `
            <div class="alert ${className}">
                <i class="${icon} me-2"></i>
                ${message}
            </div>
        `;
    }
    
    /**
     * Show vendor bill status message
     */
    function showVendorBillStatus(type, message) {
        let icon, className;
        
        switch (type) {
            case 'success':
                icon = 'fas fa-check-circle';
                className = 'alert-success';
                break;
            case 'error':
                icon = 'fas fa-exclamation-circle';
                className = 'alert-danger';
                break;
            case 'warning':
                icon = 'fas fa-exclamation-triangle';
                className = 'alert-warning';
                break;
            case 'info':
            default:
                icon = 'fas fa-info-circle';
                className = 'alert-info';
                break;
        }
        
        vendorBillStatus.innerHTML = `
            <div class="alert ${className}">
                <i class="${icon} me-2"></i>
                ${message}
            </div>
        `;
    }
    
    /**
     * Update processing step status
     */
    function updateStepStatus(element, status) {
        // Remove existing status classes
        element.classList.remove('step-pending', 'step-processing', 'step-complete', 'step-error');
        
        // Add appropriate icon and class
        let icon, className;
        
        switch (status) {
            case 'complete':
                icon = 'fas fa-check-circle text-success';
                className = 'step-complete';
                break;
            case 'processing':
                icon = 'fas fa-spinner fa-spin text-primary';
                className = 'step-processing';
                break;
            case 'error':
                icon = 'fas fa-times-circle text-danger';
                className = 'step-error';
                break;
            case 'pending':
            default:
                icon = 'fas fa-circle text-secondary';
                className = 'step-pending';
                break;
        }
        
        element.classList.add(className);
        
        // Update icon
        const iconElement = element.querySelector('.step-icon');
        iconElement.className = `${icon} step-icon`;
    }
    
    /**
     * Reset processing UI elements
     */
    function resetProcessingUI() {
        // Hide invoice details
        invoiceDetailsContainer.classList.add('d-none');
        
        // Reset step status
        updateStepStatus(stepUpload, 'pending');
        updateStepStatus(stepParse, 'pending');
        updateStepStatus(stepCreate, 'pending');
        
        // Reset status messages
        showStatus('info', 'Ready to process your invoice.');
        vendorBillStatus.innerHTML = '';
        
        // Hide processing steps
        processingSteps.classList.add('d-none');
    }
    
    /**
     * Format date string
     */
    function formatDate(dateString) {
        if (!dateString) return '';
        
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        } catch (error) {
            console.error('Error formatting date:', error);
            return dateString;
        }
    }
    
    /**
     * Format currency value
     */
    function formatCurrency(value) {
        if (value === undefined || value === null) return '';
        
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(value);
    }
    
    /**
     * Format invoice status
     */
    function formatStatus(status) {
        let badgeClass, icon;
        
        switch (status) {
            case 'uploaded':
                badgeClass = 'bg-secondary';
                icon = 'fas fa-upload';
                break;
            case 'processing':
                badgeClass = 'bg-primary';
                icon = 'fas fa-spinner fa-spin';
                break;
            case 'parsed':
                badgeClass = 'bg-info';
                icon = 'fas fa-file-alt';
                break;
            case 'completed':
                badgeClass = 'bg-success';
                icon = 'fas fa-check-circle';
                break;
            case 'error':
                badgeClass = 'bg-danger';
                icon = 'fas fa-exclamation-circle';
                break;
            default:
                badgeClass = 'bg-secondary';
                icon = 'fas fa-question-circle';
                break;
        }
        
        return `<span class="badge ${badgeClass}"><i class="${icon} me-1"></i>${status}</span>`;
    }
});
