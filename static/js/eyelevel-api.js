/**
 * Eyelevel.ai API integration for invoice parsing
 * 
 * This file contains utilities for interacting with the Eyelevel.ai API
 * for document processing and data extraction.
 */

// Eyelevel API class
class EyelevelAPI {
    /**
     * Parse an invoice document using Eyelevel.ai
     * 
     * Note: This is handled server-side in this application
     * but this client-side utility is provided for reference
     * and potential future direct API integration.
     * 
     * @param {File} file - The invoice file to parse
     * @returns {Promise} - Promise with parsed data
     */
    static parseInvoice(file) {
        return new Promise((resolve, reject) => {
            // Create form data
            const formData = new FormData();
            formData.append('file', file);
            
            // Send to server endpoint
            fetch('/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Server returned ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    resolve(data);
                } else {
                    reject(new Error(data.error || 'Unknown error parsing invoice'));
                }
            })
            .catch(error => {
                reject(error);
            });
        });
    }
    
    /**
     * Extract structured data from Eyelevel.ai response
     * 
     * @param {Object} eyelevelResponse - The raw Eyelevel.ai API response
     * @returns {Object} - Structured invoice data
     */
    static extractInvoiceData(eyelevelResponse) {
        // This is a helper method to extract and normalize data
        // from the Eyelevel.ai API response format
        
        try {
            // Extract basic invoice details
            const invoiceData = {
                vendor_name: eyelevelResponse.vendor?.name || '',
                invoice_number: eyelevelResponse.invoice_number || '',
                invoice_date: eyelevelResponse.date || '',
                due_date: eyelevelResponse.due_date || '',
                total_amount: parseFloat(eyelevelResponse.total_amount || 0),
                line_items: []
            };
            
            // Extract line items
            if (eyelevelResponse.line_items && Array.isArray(eyelevelResponse.line_items)) {
                invoiceData.line_items = eyelevelResponse.line_items.map(item => ({
                    description: item.description || '',
                    quantity: parseFloat(item.quantity || 1),
                    unit_price: parseFloat(item.unit_price || 0),
                    amount: parseFloat(item.amount || 0),
                    tax: parseFloat(item.tax || 0)
                }));
            }
            
            return invoiceData;
        } catch (error) {
            console.error('Error extracting invoice data:', error);
            throw new Error('Failed to extract invoice data from Eyelevel response');
        }
    }
}

// If using as a module
if (typeof module !== 'undefined' && module.exports) {
    module.exports = EyelevelAPI;
}
