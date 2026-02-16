from fastapi import FastAPI, BackgroundTasks, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import os
import shutil
import socket
import json
import asyncio
from datetime import datetime, timedelta

from app.services.google_sheets import GoogleSheetService
from app.services.qr_generator import QRGenerator
from app.services.whatsapp import whatsapp_service
from app.services.crypto import crypto_service
from app.config import settings

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/generated_qrs", StaticFiles(directory="generated_qrs"), name="generated_qrs")

templates = Jinja2Templates(directory="templates")

# Initialize services
qr_generator = QRGenerator()
google_sheet_service = GoogleSheetService()

def get_local_ip():
    try:
        # Connect to a public DNS to determine local IP used for routing
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

# Global state for active sessions
active_sessions = {}
SESSION_FILE = "sessions.json"
STATE_FILE = "server_state.json"

def save_sessions():
    """Saves active sessions to JSON file."""
    try:
        data = {}
        for tid, session in active_sessions.items():
            data[tid] = {
                "name": session["name"],
                "phone": session["phone"],
                "transaction_id": session["transaction_id"],
                "duration": session["duration"],
                "start_time": session["start_time"].isoformat(),
                "end_time": session["end_time"].isoformat(),
                "restore_key": session.get("restore_key") # Save restore key
            }
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f, indent=4)
        print("Sessions saved to disk.")
    except Exception as e:
        print(f"Failed to save sessions: {e}")

def load_sessions():
    """Loads sessions from JSON file."""
    global active_sessions
    try:
        import os
        if not os.path.exists(SESSION_FILE):
            return

        with open(SESSION_FILE, "r") as f:
            data = json.load(f)
            
        for tid, session in data.items():
            active_sessions[tid] = {
                "name": session["name"],
                "phone": session["phone"],
                "transaction_id": session["transaction_id"],
                "duration": session["duration"],
                "start_time": datetime.fromisoformat(session["start_time"]),
                "end_time": datetime.fromisoformat(session["end_time"]),
                "restore_key": session.get("restore_key") # Load restore key
            }
        print(f"Loaded {len(active_sessions)} sessions from disk.")
    except Exception as e:
        print(f"Failed to load sessions: {e}")

def load_server_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading server state: {e}")
    return {}

def save_server_state(data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving server state: {e}")

@app.on_event("startup")
async def startup_event():
    global active_sessions
    # Start WhatsApp service
    whatsapp_service.start()
    
    # Initialize Google Sheets Service
    print("Initializing Google Sheets Service...")
    try:
        google_sheet_service.connect()
        print("Google Sheets Service initialized successfully.")
    except Exception as e:
        print(f"Error initializing Google Sheets Service: {e}")

    load_sessions()
    
    # Cleanup expired sessions
    now = datetime.now()
    initial_count = len(active_sessions)
    active_sessions = {
        tid: session 
        for tid, session in active_sessions.items() 
        if session["end_time"] > now
    }
    
    if len(active_sessions) < initial_count:
        print(f"Cleaned up {initial_count - len(active_sessions)} expired sessions on startup.")
        save_sessions()

    # Start Hourly Stats Task
    asyncio.create_task(hourly_stats_task())
    
    # Restore timers for active sessions
    now = datetime.now()
    for tid, session in active_sessions.items():
        # Check buffer time again just in case, but main check is done above
        if session["end_time"] > now:
            remaining_seconds = (session["end_time"] - now).total_seconds()
            remaining_minutes = remaining_seconds / 60
            print(f"Restoring timer for {session['name']} ({remaining_minutes:.2f} mins left)")
            asyncio.create_task(session_timer_task(session["phone"], session["duration"], tid, is_resume=True, resume_seconds=remaining_seconds))

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/submit_entry")
async def submit_entry(
    background_tasks: BackgroundTasks, 
    name: str = Form(...),
    phone: str = Form(...),
    transaction_id: str = Form(None),
    plan_selection: str = Form(...),
    payment_mode: str = Form(...)
):
    """
    Endpoint to trigger individual processing.
    """
    # Validate Transaction ID for Online payments
    if payment_mode == "online":
         if not transaction_id:
             return JSONResponse(
                 status_code=400,
                 content={"status": "Error", "message": "Transaction ID is required for Online payments"}
             )
         # Check for duplicate transaction ID
         if settings.SHEET_URL:
             if google_sheet_service.check_transaction_exists(settings.SHEET_URL, transaction_id):
                 return JSONResponse(
                     status_code=400, 
                     content={"status": "Error", "message": "Transaction ID already exists"}
                 )
    else:
        # Generate Cash Transaction ID
        import random
        # Format: CASH-YYYYMMDD-HHMMSS-XXX
        timestamp_part = datetime.now().strftime("%Y%m%d-%H%M%S")
        random_part = str(random.randint(100, 999))
        transaction_id = f"CASH-{timestamp_part}-{random_part}"

    background_tasks.add_task(process_entry_task, name, phone, transaction_id, plan_selection, payment_mode)
    return {"status": "Processing started", "message": "QR generation initiated"}

@app.get("/verify", response_class=HTMLResponse)
async def verify_entry(request: Request, token: str):
    """
    Verifies entry based on encrypted token and secure key.
    """
    try:
        # Decrypt Token
        try:
            data = crypto_service.decrypt(token)
            transaction_id = data.get("transaction_id")
            name = data.get("name")
            phone = data.get("phone")
            duration = data.get("duration", 15)
            plan = data.get("plan", "Unknown") # New Field
            secure_key = data.get("secure_key")
        except Exception:
            return templates.TemplateResponse("scan_result.html", {
                "request": request,
                "status": "error",
                "message": "Invalid or Tampered QR Code"
            })

        # Validate Security Key
        # 1. Check if ACTIVE SESSION exists (Reload support)
        # We check this FIRST because if a session is active, the key is already removed from pending_keys,
        # so the pending_keys check below would assume it's invalid/expired.
        if transaction_id in active_sessions:
             return templates.TemplateResponse("scan_result.html", {
                "request": request,
                "status": "check_restore",
                "transaction_id": transaction_id,
                "name": name,
                "phone": phone, 
                "duration": duration,
                "plan": plan
            })

        # 2. Validate Security Key (Pending Session)
        if transaction_id not in pending_keys:
             # Check if already processed (not in pending lists)
             current_status = google_sheet_service.get_entry_status(transaction_id)
             if current_status and current_status.strip().lower() == "in":
                 return templates.TemplateResponse("scan_result.html", {
                    "request": request,
                    "status": "error",
                    "message": "Entry ALREADY processed/used."
                 })
             else:
                 return templates.TemplateResponse("scan_result.html", {
                    "request": request,
                    "status": "error",
                    "message": "Invalid QR Code: Transaction not found or expired."
                 })
        
        if pending_keys[transaction_id] != secure_key:
             return templates.TemplateResponse("scan_result.html", {
                "request": request,
                "status": "error",
                "message": "Security Check Failed: Invalid Key."
            })

        # Check current status
        # If transaction is in pending_keys, we allow "In" status (re-scan case).
        # If transaction is NOT in pending_keys, it is handled by the first check.
        
        # Update Google Sheets
        google_sheet_service.update_entry_status(transaction_id, "In")
        
        # Note: We do NOT remove the key here anymore. 
        # It will be removed in /start_timer to allow re-scanning if browser is closed.
        
        # Send WhatsApp Message
        msg = f"Welcome {name}! Your entry is confirmed. Please ask the admin to start your {duration} mins session."
        whatsapp_service.send_message(phone, msg)
        
        return templates.TemplateResponse("scan_result.html", {
            "request": request,
            "status": "success",
            "name": name,
            "transaction_id": transaction_id,
            "duration": duration,
            "plan": plan,
            "phone": phone, # Needed for starting timer
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        print(f"Verification Failed: {e}")
        return templates.TemplateResponse("scan_result.html", {
            "request": request,
            "status": "error",
            "message": "Verification Processing Failed"
        })

# Global state for pending keys (Security)
PENDING_KEYS_FILE = "pending_keys.json"
pending_keys = {}

def load_pending_keys():
    """Loads pending keys from JSON file."""
    global pending_keys
    try:
        if os.path.exists(PENDING_KEYS_FILE):
            with open(PENDING_KEYS_FILE, "r") as f:
                pending_keys = json.load(f)
        print(f"Loaded {len(pending_keys)} pending keys.")
    except Exception as e:
        print(f"Failed to load pending keys: {e}")

def save_pending_keys():
    """Saves pending keys to JSON file."""
    try:
        with open(PENDING_KEYS_FILE, "w") as f:
            json.dump(pending_keys, f, indent=4)
    except Exception as e:
        print(f"Failed to save pending keys: {e}")

# Load keys on startup
load_pending_keys()

def process_entry_task(name: str, phone: str, transaction_id: str, plan_selection: str, payment_mode: str):
    from app.config import log_debug
    import secrets
    log_debug(f"Starting task for: {name}, {phone}, {transaction_id}, {plan_selection}, {payment_mode}")
    
    # Parse Plan
    try:
        if plan_selection == "premium_50":
            amount = 50
            duration = 15
            plan_name = "Premium"
        elif plan_selection == "standard_40":
            amount = 40
            duration = 15
            plan_name = "Standard"
        else:
            # Fallback or Error
            amount = 0
            duration = 0
            plan_name = "Unknown"
    except Exception:
        amount = 0
        duration = 0
        plan_name = "Error"
    
    # 1. Clean Phone
    phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    
    # 2. Generate 14-digit Secure Key
    secure_key = str(secrets.randbelow(10**14)).zfill(14)
    
    # Store key
    pending_keys[transaction_id] = secure_key
    save_pending_keys()
    
    # 3. Generate QR Data (Encrypted Token with Key)
    data = {
        "transaction_id": transaction_id,
        "name": name,
        "phone": phone,
        "duration": duration,
        "amount": amount,
        "plan": plan_name,
        "secure_key": secure_key
    }
    
    try:
        token = crypto_service.encrypt(data)
        
        # Build URL
        local_ip = get_local_ip()
        port = 5000
        qr_data = f"http://{local_ip}:{port}/verify?token={token}"
        log_debug(f"QR Content: {qr_data}")
        
    except Exception as e:
        log_debug(f"Encryption failed: {e}")
        return
    
    # 4. Generate QR Image
    try:
        qr_path = qr_generator.generate_qr(qr_data)
        log_debug(f"Generated QR at {qr_path}")
    except Exception as e:
        log_debug(f"QR Generation failed: {e}")
        return

    # 5. Save to Google Sheets
    if settings.SHEET_URL:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Order: Timestamp, Name, Phone, Transaction ID, Amount, Duration, Status, Payment Mode, Plan
            row_data = [timestamp, name, phone, transaction_id, amount, duration, "Pending", payment_mode, plan_name]
            google_sheet_service.append_data(settings.SHEET_URL, row_data)
        except Exception as e:
            log_debug(f"Failed to save to Google Sheets: {e}")
    else:
        log_debug("Skipping Google Sheets save: SHEET_URL not set.")

    # 6. Send Message via WhatsApp
    caption = f"Hello {name}, your {payment_mode} transaction ({transaction_id}) for {plan_name} - INR {amount} ({duration} mins) is confirmed. Here is your unique QR code."
    
    try:
        log_debug(f"Attempting to send QR to {phone}")
        success = whatsapp_service.send_image(phone, qr_path, caption)
        if success:
            log_debug(f"Sent QR to {name} ({phone})")
        else:
            log_debug(f"Failed to send QR to {name} ({phone})")
    except Exception as e:
        log_debug(f"Error sending WhatsApp message: {e}")

async def hourly_stats_task():
    """Background task to send hourly statistics (Persistent)."""
    print("Starting Hourly Stats Task...")
    
    while True:
        try:
            state = load_server_state()
            last_report_str = state.get("last_hourly_report")
            
            now = datetime.now()
            
            if last_report_str:
                last_report_time = datetime.fromisoformat(last_report_str)
                next_report_time = last_report_time + timedelta(hours=1)
                wait_seconds = (next_report_time - now).total_seconds()
            else:
                last_report_time = now
                save_server_state({"last_hourly_report": now.isoformat()})
                wait_seconds = 3600
            
            print(f"Hourly Stats: Last run {last_report_time}, Next run in {wait_seconds:.2f}s")
            
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            
            # --- Perform Task ---
            stats = google_sheet_service.get_stats_for_today(settings.SHEET_URL)
            
            msg = (
                f"Hourly Report\n"
                f"Date: {datetime.now().strftime('%Y-%m-%d')}\n"
                f"Total Entries: {stats['count']}\n"
                f"Total Collected: INR {stats['total']}"
            )
            
            print(f"Sending Hourly Report: {msg}")
            whatsapp_service.send_message(settings.ADMIN_PHONE, msg)
            
            # --- Update State ---
            new_now = datetime.now()
            save_server_state({"last_hourly_report": new_now.isoformat()})
            
            await asyncio.sleep(1) 
            
        except Exception as e:
            print(f"Error in hourly stats task: {e}")
            await asyncio.sleep(60)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = f"Server Error\nPath: {request.url.path}\nError: {str(exc)}"
    print(error_msg)
    
    try:
        whatsapp_service.send_message(settings.ADMIN_PHONE, error_msg)
    except Exception as e:
        print(f"Failed to send error alert: {e}")
        
    return JSONResponse(
        status_code=500,
        content={"message": "Internal Server Error", "details": str(exc)},
    )

@app.post("/start_timer")
async def start_timer(
    background_tasks: BackgroundTasks,
    phone: str = Form(...),
    duration: str = Form(...),
    name: str = Form(None),
    transaction_id: str = Form(None)
):
    print(f"DEBUG START TIMER: phone={phone}, duration={duration}, name={name}, tid={transaction_id}")
    
    if not name or not transaction_id:
        return JSONResponse(status_code=400, content={"status": "Error", "message": "Missing name or transaction_id"})

    try:
        duration_int = int(duration)
    except ValueError:
        duration_int = 15 

    # Store session info
    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_int)
    
    active_sessions[transaction_id] = {
        "name": name,
        "phone": phone,
        "transaction_id": transaction_id,
        "duration": duration_int,
        "start_time": start_time,
        "end_time": end_time
    }
    
    save_sessions()

    # Remove Secure Key (Now it is truly used)
    if transaction_id in pending_keys:
        del pending_keys[transaction_id]
        save_pending_keys()

    # Generate Restore Key
    import secrets
    restore_key = secrets.token_urlsafe(12) # approx 16 chars
    active_sessions[transaction_id]["restore_key"] = restore_key
    save_sessions()

    background_tasks.add_task(session_timer_task, phone, duration_int, transaction_id)
    return {
        "status": "Timer started",
        "end_time": end_time.isoformat(),
        "duration": duration_int,
        "restore_key": restore_key
    }

@app.post("/api/verify_restore")
async def verify_restore(request: Request):
    """
    Verifies a restore key for an active session.
    """
    try:
        data = await request.json()
        transaction_id = data.get("transaction_id")
        restore_key = data.get("restore_key")
        
        if transaction_id in active_sessions:
            session = active_sessions[transaction_id]
            if session.get("restore_key") == restore_key:
                return {
                    "status": "restored",
                    "end_time": session["end_time"].isoformat(),
                    "duration": session["duration"],
                    "start_time": session["start_time"].isoformat()
                }
        
        return JSONResponse(status_code=403, content={"status": "error", "message": "Invalid Restore Key or Session Ended"})
        
    except Exception as e:
        print(f"Restore verification failed: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": "Server Error"})

@app.get("/participants", response_class=HTMLResponse)
async def view_participants(request: Request):
    return templates.TemplateResponse("participants.html", {"request": request})

@app.get("/health", response_class=HTMLResponse)
async def view_health(request: Request):
    auth_cookie = request.cookies.get("health_auth")
    authenticated = auth_cookie == "true"
    return templates.TemplateResponse("health.html", {"request": request, "authenticated": authenticated})

@app.post("/health/login", response_class=HTMLResponse)
async def health_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        # Check where checking came from
        referer = request.headers.get("referer")
        redirect_url = "/health" # default
        
        # Simple hack: if we want to redirect back to /data if possible, but form doesn't carry it easily without hidden field.
        # For now, always Health. But let's support /data access.
        
        response = templates.TemplateResponse("health.html", {"request": request, "authenticated": True})
        response.set_cookie(key="health_auth", value="true", httponly=True)
        return response
    else:
        return templates.TemplateResponse("health.html", {
            "request": request, 
            "authenticated": False, 
            "error": "Invalid Credentials"
        })

@app.get("/data", response_class=HTMLResponse)
async def view_data(request: Request):
    # Reuse Health Auth
    auth_cookie = request.cookies.get("health_auth")
    if auth_cookie != "true":
         # Redirect to login (Health page for now as it has the form)
         return RedirectResponse(url="/health", status_code=302)
    
    # Fetch Data
    stats = google_sheet_service.get_total_stats(settings.SHEET_URL)
    
    return templates.TemplateResponse("data.html", {
        "request": request, 
        "total_participants": stats["count"],
        "total_revenue": stats["total"]
    })

@app.get("/health/logout", response_class=HTMLResponse)
def health_logout(request: Request):
    response = RedirectResponse(url="/health", status_code=302)
    response.delete_cookie("health_auth")
    # RedirectResponse requires import, let's use TemplateResponse to be lazy or import it.
    # Actually, returning a template with cleared cookie is fine, or simple redirect.
    # Let's verify imports first. RedirectResponse is in fastapi.responses
    return response

@app.get("/api/health_stats")
async def get_health_stats():
    return {
        "active_sessions": len(active_sessions),
        "server_time": datetime.now().isoformat()
    }

@app.get("/api/sessions")
async def get_sessions():
    now = datetime.now()
    sessions_list = []
    
    for tid, session in active_sessions.items():
        remaining = (session["end_time"] - now).total_seconds()
        status = "Active"
        if remaining <= 0:
            remaining = 0
            status = "Ended"
        elif remaining <= (settings.WARNING_BUFFER_MINUTES * 60):
            status = "Warning"
            
        sessions_list.append({
            "name": session["name"],
            "phone": session["phone"],
            "transaction_id": session["transaction_id"],
            "duration": session["duration"],
            "start_time": session["start_time"].strftime("%H:%M:%S"),
            "end_time": session["end_time"].strftime("%H:%M:%S"),
            "remaining_seconds": int(remaining),
            "status": status
        })
        
    return sessions_list

async def session_timer_task(phone: str, duration: int, transaction_id: str, is_resume: bool = False, resume_seconds: float = None):
    from app.config import log_debug
    # Global variables for session management
    global active_sessions
    
    loop = asyncio.get_event_loop()
    
    try:
        log_debug(f"Timer task START: {phone}, {duration}m, resume={is_resume}, remaining={resume_seconds}")
        
        if not is_resume:
            try:
                msg = f"Your {duration} minutes session has STARTED now. Have fun!"
                log_debug(f"Sending start msg to {phone}")
                # Use executor to avoid blocking async loop since send_message might sleep/wait
                await loop.run_in_executor(None, whatsapp_service.send_message, phone, msg)
                log_debug(f"Start msg sent to {phone}")
            except Exception as e:
                log_debug(f"Failed to send start message: {e}")
        
        warning_buffer_mins = settings.WARNING_BUFFER_MINUTES
        total_seconds = duration * 60
        warning_time_seconds = (duration - warning_buffer_mins) * 60
        
        # Calculate how much time to sleep until warning
        if is_resume and resume_seconds is not None:
             # We are resuming.
             # Time already elapsed = Total - Remaining
             elapsed = total_seconds - resume_seconds
             
             # Time until warning triggers
             sleep_until_warning = warning_time_seconds - elapsed
        else:
             sleep_until_warning = warning_time_seconds

        # 1. Sleep until Warning Time
        if sleep_until_warning > 0:
            log_debug(f"Sleeping {sleep_until_warning}s until warning for {phone}")
            await asyncio.sleep(sleep_until_warning)
            
            # Send Warning
            try:
                msg = f"Warning: You have {warning_buffer_mins} minutes remaining in your session."
                log_debug(f"Sending warning to {phone}")
                await loop.run_in_executor(None, whatsapp_service.send_message, phone, msg)
                log_debug(f"Sent warning to {phone}")
            except Exception as e:
                log_debug(f"Failed to send warning: {e}")
                
            # Sleep remaining buffer time
            remaining_after_warning = total_seconds - warning_time_seconds # Should be buffer * 60
            log_debug(f"Sleeping remaining {remaining_after_warning}s after warning for {phone}")
            await asyncio.sleep(remaining_after_warning)
            
        else:
            # We are PAST the warning time (or warning time is 0/negative)
            # Just sleep the remaining duration
            remaining = resume_seconds if (is_resume and resume_seconds is not None) else total_seconds
            
            if remaining > 0:
                log_debug(f"Past warning time. Sleeping remaining {remaining}s for {phone}")
                await asyncio.sleep(remaining)

    except asyncio.CancelledError:
        log_debug(f"Timer task cancelled for {transaction_id}")
        raise
    except Exception as e:
        log_debug(f"CRITICAL ERROR in session_timer_task: {e}")
        
    # Time Ended - Cleanup
    try:
        msg = f"Your session time of {duration} minutes has ended. Please proceed to exit."
        await loop.run_in_executor(None, whatsapp_service.send_message, phone, msg)
        log_debug(f"Sent ended message to {phone}")
        
        # Remove from active sessions
        if transaction_id in active_sessions:
            del active_sessions[transaction_id]
            save_sessions()
            log_debug(f"Session {transaction_id} expired and removed.")
            
    except Exception as e:
        log_debug(f"Failed to send ended message: {e}")
