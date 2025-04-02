# Invoice Parser Application

An advanced invoice processing application that leverages AI-powered document reading technology to streamline vendor bill creation. The system integrates Eyelevel.ai for intelligent document parsing and connects with Zoho Books via Deluge script to automate financial workflows.

## Key Technologies
- AI-powered OCR (Eyelevel.ai)
- Zoho Books Integration
- JavaScript Frontend
- Python Backend (Flask)
- RESTful API Connectivity

## Features
- Upload invoices in PDF or image format
- Automatic data extraction with OCR
- View parsed invoice data
- Create vendor bills in Zoho Books
- Manage invoice history

## Setup
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables:
   - `EYELEVEL_API_KEY`: For Eyelevel.ai OCR functionality
   - `ZOHO_API_KEY`: For Zoho Books integration
4. Run the application: `python main.py`

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