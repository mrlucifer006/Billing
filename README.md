# Ticket System - Developer Guide

Welcome to the Ticket System codebase (formerly GDC Billing System). This guide is designed to help new developers understand the architecture, setup the project, and contribute effectively.

## 1. Project Overview

The Ticket System is a web-based application used to manage event ticketing and entry. It handles:
-   **User Entries**: Recording participant details, payment mode (Cash/Online), and selected ticket type.
-   **QR Code Generation**: Generating secure, encrypted QR codes for entry verification.
-   **Verification**: Scanning QR codes to verify transactions and confirm entry.
-   **Session Management**: Tracking active sessions and sending WhatsApp notifications.
-   **Data Logging**: Automatically saving all transaction details to a Google Sheet.

## 2. Technology Stack

-   **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python) - High performance, easy to use.
-   **Frontend**: HTML, JavaScript, [Tailwind CSS](https://tailwindcss.com/) (via CDN).
-   **Database**:
    -   **Google Sheets**: Used as the primary persistent storage for transaction logs.
    -   **JSON Files**: `sessions.json`, `pending_keys.json` for local state management.
    -   **SQLite**: Used internally by the WhatsApp library (`neonize`).
-   **WhatsApp Integration**: [Neonize](https://github.com/krypton-byte/neonize) (Python wrapper for `whatsmeow`).
-   **Encryption**: Fernet (symmetric encryption) for secure QR code tokens.

## 3. Project Structure

```
Billing/
├── app/
│   ├── main.py              # Application entry point, API routes, and task logic
│   ├── config.py            # Configuration settings (environment variables)
│   └── services/            # Business logic modules
│       ├── crypto.py        # Encryption service for QR tokens
│       ├── google_sheets.py # Google Sheets API wrapper
│       ├── qr_generator.py  # QR code generation logic
│       └── whatsapp.py      # WhatsApp message sending service
├── templates/               # HTML Templates (Jinja2)
│   ├── index.html           # Main submission form
│   ├── scan_result.html     # Verification result & timer page
│   ├── health.html          # Server health dashboard
│   ├── data.html            # Financial data dashboard
│   ├── participants.html    # Live participants view
├── static/                  # Static assets (CSS/JS if needed locally)
├── generated_qrs/           # Temporary storage for generated QR images
├── credentials.json         # Google Cloud Service Account credentials (DO NOT COMMIT)
├── authorized_user.json     # Google OAuth user token (DO NOT COMMIT)
├── .env                     # Environment variables (DO NOT COMMIT)
├── run.py                   # Script to start the server (Uvicorn)
└── requirements.txt         # Python dependencies
```

## 4. Key Components & Workflows

### A. Submission Flow (`/submit_entry`)
1.  **Frontend**: User selects Payment Mode (Online/Cash) and Ticket Type (Premium/Standard).
2.  **Validation**:
    -   **Online**: Requires a Transaction ID.
    -   **Cash**: Backend generates a unique ID (`CASH-YYYYMMDD...`).
3.  **Processing** (`process_entry_task`):
    -   Generates a secure 14-digit key.
    -   Encrypts data into a token.
    -   Generates a QR code containing the verification URL.
    -   Appends data to Google Sheets.
    -   Sends the QR code to the user via WhatsApp.

### B. Verification Flow (`/verify`)
1.  **Scanning**: Admin scans the user's QR code.
2.  **Decryption**: Backend decrypts the token to get details.
3.  **Validation**:
    -   Checks if the transaction ID exists in `pending_keys.json`.
    -   Verifies the secure key matches.
    -   Checks if the entry has already been used.
4.  **Result**: Displays the user details and a "Start Timer" button.

### C. Session Timer
1.  **Start**: Admin clicks "Start Timer".
2.  **Tracking**: Session is added to `active_sessions` (memory + `sessions.json`).
3.  **Notifications**: WhatsApp messages are sent at start, warning (5 mins before), and end.

## 5. Setup Instructions

### Prerequisites
-   Python 3.10+
-   Google Cloud Service Account (for Sheets API)

### Installation
1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configuration**:
    -   Place `credentials.json` in the root directory.
    -   Create a `.env` file with:
        ```env
        SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID
        ADMIN_PHONE=91XXXXXXXXXX
        SECRET_KEY=your_fernet_key
        ```

### Running the Server
```bash
python run.py
```
Access the app at `http://localhost:5000` (or your local IP).

## 6. Google Sheets Schema

The application expects the following columns in order (A-I):

1.  **Timestamp** (A)
2.  **Name** (B)
3.  **Phone** (C)
4.  **Transaction ID** (D)
5.  **Amount** (E)
6.  **Duration** (F)
7.  **Status** (G)
8.  **Payment Mode** (H)
9.  **Plan** (I)

> **Important**: Changing column order requires updating `app/services/google_sheets.py`.

## 7. Troubleshooting

-   **WhatsApp not working**: Delete `my_session.sqlite3` and restart to re-scan the QR code.
-   **Google Sheets Error**: Ensure `credentials.json` is valid and the service account has Editor access to the sheet.
-   **Template Not Found**: Ensure you are running `run.py` from the root directory.

---
*Maintained by sanjai M S*
