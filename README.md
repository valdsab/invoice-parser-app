# Invoice Parser Application

An advanced invoice processing application that leverages AI-powered document reading technology to streamline vendor bill creation. The system integrates LlamaCloud API for intelligent document parsing and connects with Zoho Books via Deluge script to automate financial workflows.

## Key Technologies
- AI-powered OCR (LlamaCloud API)
- Zoho Books Integration
- JavaScript Frontend
- Python Backend (Flask)
- RESTful API Connectivity
- PostgreSQL Database

## Features
- Upload invoices in PDF or image format
- Automatic data extraction with OCR
- View parsed invoice data
- Create vendor bills in Zoho Books
- Manage invoice history
- Vendor-specific field mapping for consistent parsing
- Secure MIME-type validation for file uploads
- Enhanced JSON field support for storing complex data

## Setup
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables:
   - `LLAMA_CLOUD_API_ENTOS`: For LlamaCloud API access
   - `ZOHO_API_KEY`: For Zoho Books integration (when ready to implement)
   - `DATABASE_URL`: PostgreSQL database connection URL
4. Run the application: `gunicorn --bind 0.0.0.0:5000 main:app`

## Project Structure
- `app.py`: Flask application setup
- `main.py`: Application entry point
- `models.py`: Database models
- `routes.py`: API endpoints
- `utils.py`: Utility functions
- `templates/`: HTML templates
- `static/`: CSS, JavaScript, and other static assets

## Screenshots
(Screenshots will be added here)

## License
MIT