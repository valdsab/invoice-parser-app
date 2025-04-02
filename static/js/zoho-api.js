/**
 * Zoho Books API integration for vendor bill creation
 * 
 * This file contains utilities for interacting with the Zoho Books API
 * via Deluge script to create vendor bills.
 */

// Zoho API class
class ZohoAPI {
    /**
     * Create a vendor bill in Zoho Books
     * 
     * Note: This is handled server-side in this application
     * but this client-side utility is provided for reference
     * and potential future direct API integration.
     * 
     * @param {Number} invoiceId - The ID of the parsed invoice
     * @returns {Promise} - Promise with creation result
     */
    static createVendorBill(invoiceId) {
        return new Promise((resolve, reject) => {
            if (!invoiceId) {
                reject(new Error('Invoice ID is required'));
                return;
            }
            
            // Send request to server endpoint
            fetch(`/create_vendor_bill/${invoiceId}`, {
                method: 'POST'
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
                    reject(new Error(data.error || 'Unknown error creating vendor bill'));
                }
            })
            .catch(error => {
                reject(error);
            });
        });
    }
    
    /**
     * Format invoice data for Zoho Books vendor bill creation
     * 
     * @param {Object} invoiceData - The parsed invoice data
     * @returns {Object} - Formatted data for Zoho Books API
     */
    static formatVendorBillData(invoiceData) {
        // This is a helper method to format data for the Zoho Books API
        
        try {
            // Format basic vendor bill details
            const vendorBillData = {
                vendor_name: invoiceData.vendor_name,
                bill_number: invoiceData.invoice_number,
                date: invoiceData.invoice_date,
                due_date: invoiceData.due_date,
                total: invoiceData.total_amount,
                line_items: []
            };
            
            // Format line items
            if (invoiceData.line_items && Array.isArray(invoiceData.line_items)) {
                vendorBillData.line_items = invoiceData.line_items.map(item => ({
                    name: item.description,
                    quantity: item.quantity,
                    rate: item.unit_price,
                    tax: item.tax || 0
                }));
            }
            
            return vendorBillData;
        } catch (error) {
            console.error('Error formatting vendor bill data:', error);
            throw new Error('Failed to format vendor bill data for Zoho Books');
        }
    }
}

// If using as a module
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ZohoAPI;
}
