import os
import threading
import time
import logging
from neonize.client import NewClient
from neonize.events import ConnectedEv, PairStatusEv, Event
from neonize.utils import log
from neonize.utils.jid import build_jid
from neonize.proto.Neonize_pb2 import Message

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.config import settings

class WhatsAppService:
    def __init__(self, session_name: str = None):
        if session_name is None:
            session_name = settings.WHATSAPP_SESSION_NAME
        self.session_name = session_name
        self.client = NewClient(session_name + ".sqlite3")
        self.is_connected = False
        self.qr_callback = None
        
        # Setup event listeners
        @self.client.event(ConnectedEv)
        def on_connected(client, event: ConnectedEv):
            from app.config import log_debug
            log_debug("WhatsApp Connected")
            self.is_connected = True

        @self.client.event(PairStatusEv)
        def on_pair_status(client, event: PairStatusEv):
            from app.config import log_debug
            log_debug(f"Pair Status: {event}")

    def start(self):
        """Starts the neonize client in a separate thread."""
        def run_client():
            from app.config import log_debug
            log_debug("Starting WhatsApp Client Thread...")
            
            while True:
                try:
                    # self.client.connect() DOES BLOCK, so we should just call it.
                    # If it returns or errors, we restart.
                    self.client.connect()
                except Exception as e:
                    log_debug(f"WhatsApp client disconnected/error: {e}. Reconnecting in 5s...")
                    self.is_connected = False
                    time.sleep(5)

        self.thread = threading.Thread(target=run_client, daemon=True)
        self.thread.start()
        
    def ensure_connection(self):
        """Waits for connection with timeout."""
        if self.is_connected:
            return True
            
        from app.config import log_debug
        log_debug("Waiting for WhatsApp connection...")
        
        # Wait up to 15 seconds
        for _ in range(30):
            if self.is_connected:
                log_debug("WhatsApp connected successfully.")
                return True
            time.sleep(0.5)
            
        # Try to reconnect manually if stuck
        log_debug("Connection timed out. Checking thread status...")
        if not self.thread.is_alive():
            log_debug("Thread died, restarting...")
            self.start()
            
        return False

    def send_image(self, phone_number: str, image_path: str, caption: str = ""):
        """
        Sends an image to the specified phone number.
        phone_number should be in format '1234567890' (no + or @s.whatsapp.net, we will clean it).
        """
        from app.config import log_debug
        
        if not self.ensure_connection():
            log_debug("WhatsApp client not connected. Attempting to send anyway, might fail or queue.")

        phone_number = phone_number.strip().replace("+", "").replace(" ", "").replace("-", "")
        
        # Add default country code if missing (assuming IN +91 for 10-digit numbers)
        if len(phone_number) == 10:
            phone_number = "91" + phone_number
            
        # Build JID
        try:
            jid = build_jid(phone_number, "s.whatsapp.net")
            log_debug(f"DEBUG: Generated JID object: {jid} (Type: {type(jid)})")
        except Exception as e:
            log_debug(f"ERROR: Failed to build JID: {e}")
            return False

        try:
            log_debug(f"DEBUG: Attempting to send image to {jid} from {image_path}")
            
            # Check if file exists
            if not os.path.exists(image_path):
                log_debug(f"ERROR: Image file not found at {image_path}")
                return False

            log_debug(f"Sending image to {jid} from {image_path}")
            self.client.send_image(
                to=jid,
                file=image_path,
                caption=caption
            )
            return True
        except Exception as e:
            log_debug(f"Failed to send image: {e}")
            return False

    def send_message(self, phone_number: str, message: str):
        """
        Sends a text message to the specified phone number.
        """
        from app.config import log_debug
        
        if not self.ensure_connection():
            log_debug("WhatsApp client not connected. Attempting to send anyway.")

        phone_number = phone_number.strip().replace("+", "").replace(" ", "").replace("-", "")
        if len(phone_number) == 10:
            phone_number = "91" + phone_number

        try:
            from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
            
            jid = build_jid(phone_number, "s.whatsapp.net")
            
            msg = Message(conversation=message)
            
            self.client.send_message(
                to=jid,
                message=msg
            )
            logger.info(f"Sent message to {phone_number}: {message}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            import traceback
            traceback.print_exc()
            return False

# Global instance
whatsapp_service = WhatsAppService()

# Global instance
whatsapp_service = WhatsAppService()
