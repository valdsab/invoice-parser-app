/**
 * LlamaCloud API integration for invoice parsing
 * 
 * This file contains utilities for interacting with the LlamaCloud API
 * for document processing and data extraction.
 */

// LlamaCloud API class
class LlamaCloudAPI {
    /**
     * Parse an invoice document using LlamaCloud
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
     * Helper function to extract information from description text using regex
     * 
     * @param {string} desc - The description text to search in
     * @param {RegExp} regex - Regular expression pattern to match
     * @returns {string|null} - Extracted value or null if not found
     */
    static extractFromDesc(desc, regex) {
        if (!desc) return null;
        const match = desc.match(regex);
        return match?.[1] || null;
    }

    /**
     * Normalize invoice data across different vendors
     * 
     * @param {Object} llamaCloudData - The raw LlamaCloud API response
     * @returns {Object} - Normalized invoice data
     */
    static normalizeInvoice(llamaCloudData) {
        // Safe access helper function
        const safe = (v) => v ?? null;
        
        // Create base invoice object with normalized fields
        const invoice = {
            vendor_name: safe(llamaCloudData.vendor_name),
            invoice_number: safe(llamaCloudData.invoice_number),
            invoice_date: safe(llamaCloudData.invoice_date),
            due_date: safe(llamaCloudData.due_date),
            total_amount: parseFloat(llamaCloudData.total_amount || 0),
            line_items: []
        };
        
        // Process line items with consistent field structure
        if (Array.isArray(llamaCloudData.line_items)) {
            invoice.line_items = llamaCloudData.line_items.map(item => ({
                description: item.description || '',
                project_number: item.project_number || this.extractFromDesc(item.description, /(?:Project|PN|Job)\s*(?:Number|#|No\.?|ID)?\s*[:=\s]\s*([A-Z0-9-]+)/),
                project_name: item.project_name || '',
                activity_code: item.activity_code || this.extractFromDesc(item.description, /(?:Activity|Task)\s*(?:Code|#|No\.?)?\s*[:=\s]\s*([A-Z0-9-]+)/),
                quantity: parseFloat(item.quantity || 1),
                unit_price: parseFloat(item.unit_price || 0),
                amount: parseFloat(item.amount || 0),
                tax: parseFloat(item.tax || 0)
            }));
        }
        
        return invoice;
    }

    /**
     * Extract structured data from LlamaCloud response
     * 
     * @param {Object} llamaCloudResponse - The raw LlamaCloud API response
     * @returns {Object} - Structured invoice data
     */
    static extractInvoiceData(llamaCloudResponse) {
        // This is a helper method to extract and normalize data
        // from the LlamaCloud API response format
        
        try {
            // Use the normalizeInvoice function to standardize data across different vendors
            return this.normalizeInvoice(llamaCloudResponse);
        } catch (error) {
            console.error('Error extracting invoice data:', error);
            throw new Error('Failed to extract invoice data from LlamaCloud response');
        }
    }
}

// If using as a module
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LlamaCloudAPI;
}