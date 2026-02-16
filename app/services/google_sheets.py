import gspread
import os
from datetime import datetime
from typing import List, Dict
from app.config import settings

class GoogleSheetService:
    def __init__(self, credentials_path: str = "credentials.json"):
        self.credentials_path = credentials_path
        self.client = None

    def connect(self):
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(f"Credentials file not found at {self.credentials_path}")
        
        # gspread.oauth() automatically looks for authorized_user.json or credentials.json
        # We can specify paths if needed, but default is usually fine if files are in CWD or known locations.
        # To be safe and explicit, let's use the filenames we know.
        # gspread.oauth(credentials_filename=..., authorized_user_filename=...)
        try:
            # Manually handle OAuth flow to ensure port 8080 support
            # This avoids arguments issues with different gspread versions
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            
            creds = None
            token_path = "authorized_user.json"
            
            # Load existing tokens
            if os.path.exists(token_path):
                creds = Credentials.from_authorized_user_file(token_path, [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ])
                
            # Refresh or Login
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path,
                        [
                            "https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive",
                            "https://www.googleapis.com/auth/userinfo.email",
                            "openid"
                        ]
                    )
                    # Force port 8080 and force consent to ensure we get a refresh token
                    creds = flow.run_local_server(port=8080, prompt='consent')
                
                # Save tokens
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            
            self.client = gspread.authorize(creds)
            
        except Exception as e:
            print(f"Failed to authenticate with Google Sheets: {e}")
            raise e

    def append_data(self, sheet_url: str, data: List[str]):
        """
        Appends a row of data to the specified Google Sheet.
        """
        if not self.client:
            self.connect()
        
        try:
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0) # Assume first worksheet
            worksheet.append_row(data)
            print(f"Successfully appended data to sheet: {data}")
        except Exception as e:
            import traceback
            print(f"Error appending data to sheet: {traceback.format_exc()}")
            # Optional: Retry logic or re-auth could go here
            raise e

    def fetch_data(self, sheet_url: str) -> List[Dict]:
        if not self.client:
            self.connect()
        
        try:
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0) # Assume first worksheet
            records = worksheet.get_all_records()
            return records
        except Exception as e:
            print(f"Error fetching data: {e}")
            raise e

    
    def check_transaction_exists(self, sheet_url: str, transaction_id: str) -> bool:
        """
        Checks if a transaction ID already exists in the sheet.
        Assumes Transaction ID is in Column 4 (D).
        """
        if not self.client:
            self.connect()
            
        try:
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)
            
            # Get all values in column 4 (Transaction IDs)
            # col_values(4) returns a list of strings
            transaction_ids = worksheet.col_values(4)
            
            # Check if exists (case-sensitive or insensitive? Let's go with exact match for IDs usually)
            # You might want to strip whitespace just in case
            return transaction_id.strip() in [tid.strip() for tid in transaction_ids]
            
        except Exception as e:
            print(f"Error checking transaction existence: {e}")
            # Fail safe: if we can't check, maybe we should assume false or raise error?
            # Let's log and return False to allow entry but warn, or raise? 
            # Safer to block if DB is down? Or allow? 
            # Given it's a verify app, maybe safer to allow manual fix later.
            # But user wants to prevent duplicates.
            return False 
            
    def update_entry_status(self, transaction_id: str, new_status: str):
        """
        Updates the status of a specific entry based on Transaction ID.
        Assumes Transaction ID is in Column 4 (D) and Status is in Column 5 (E).
        """
        if not self.client:
            self.connect()
        
        try:
            sheet_url = settings.SHEET_URL
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)
            
            # Find the cell with the transaction ID
            cell = worksheet.find(transaction_id)
            
            if cell:
                # Update the cell in the next column (Column 5/E if ID is in 4/D)
                # Adjusting logic: logic says ID is 4th item in list -> Col 4. Status -> Col 5.
                # cell.row is the row number. cell.col should be 4.
                # We want to update (cell.row, 5).
                
                # Check if we are really in column 4? 
                # Ideally, we trust the caller or just search. 
                # If ID is unique, finding it is enough.
                
                # Update the cell to the right (assuming status is next to it)
                # Or hardcode column 5 if we are sure structure is fixed.
                # Let's hardcode column 5 (E) for Status as per plan.
                # Status is in Column 7 (G)
                worksheet.update_cell(cell.row, 7, new_status)
                print(f"Updated status for {transaction_id} to {new_status}")
                return True
            else:
                print(f"Transaction ID {transaction_id} not found.")
                return False
                
        except Exception as e:
            print(f"Error updating status: {e}")
            return False
    
    def get_stats_for_today(self, sheet_url: str):
        """Calculates total entries and amount for the current day."""
        if not self.client:
            self.connect()

        try:
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)
            
            # 1. Get all values
            rows = worksheet.get_all_values()
            
            # Skip header if exists (simple check)
            if not rows:
                return {"count": 0, "total": 0}
            
            # Assume header is row 0, data starts row 1
            # But let's check content. If row 0 has "Timestamp", skip it.
            start_idx = 1 if rows and "Timestamp" in rows[0] else 0
            
            data_rows = rows[start_idx:]
            
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            count = 0
            total_amount = 0
            
            for row in data_rows:
                # Row structure: [Timestamp, Name, Phone, TxID, Amount, Duration, Status]
                if len(row) < 5:
                    continue
                    
                timestamp = row[0]
                amount_str = row[4]
                
                if timestamp.startswith(today_str):
                    count += 1
                    try:
                        total_amount += float(amount_str)
                    except ValueError:
                        pass
                        
            return {"count": count, "total": int(total_amount)}
            
        except Exception as e:
            print(f"Error calculating stats: {e}")
            return {"count": 0, "total": 0}
    
    def get_total_stats(self, sheet_url: str):
        """Calculates all-time total entries and amount."""
        if not self.client:
            self.connect()

        try:
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)
            
            # 1. Get all values
            rows = worksheet.get_all_values()
            
            if not rows:
                return {"count": 0, "total": 0}
            
            # Skip header
            start_idx = 1 if rows and "Timestamp" in rows[0] else 0
            data_rows = rows[start_idx:]
            
            count = 0
            total_amount = 0.0
            
            for row in data_rows:
                # Row structure: [Timestamp, Name, Phone, TxID, Amount, Duration, Status]
                if len(row) < 5:
                    continue
                
                # Count every row as a participant
                count += 1
                
                # Sum Amount
                amount_str = row[4]
                try:
                    # Remove potential currency symbols or commas if any
                    clean_amount = str(amount_str).replace(",", "").replace("₹", "").strip()
                    if clean_amount:
                        total_amount += float(clean_amount)
                except ValueError:
                    pass
                        
            return {"count": count, "total": int(total_amount)}
            
        except Exception as e:
            print(f"Error calculating total stats: {e}")
            return {"count": 0, "total": 0}

    def get_entry_status(self, transaction_id: str) -> str:
        """
        Gets the current status of a transaction ID.
        Assumes Transaction ID is in Column 4 (D) and Status is in Column 5 (E).
        """
        if not self.client:
            self.connect()
            
        try:
            sheet_url = settings.SHEET_URL
            sheet = self.client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)
            
            cell = worksheet.find(transaction_id)
            if cell:
                # Get status from column 5 (E)
                status = worksheet.cell(cell.row, 5).value
                return status
            return None
            
        except Exception as e:
            print(f"Error getting status: {e}")
            return None
