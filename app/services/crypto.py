import os
import json
import base64
from cryptography.fernet import Fernet
from typing import Dict, Any

KEY_FILE = "secret.key"

class CryptoService:
    def __init__(self):
        self.key = self._load_key()
        self.cipher_suite = Fernet(self.key)

    def _load_key(self):
        """
        Loads the secret key from the current directory or generates a new one.
        """
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as key_file:
                return key_file.read()
        else:
            key = Fernet.generate_key()
            with open(KEY_FILE, "wb") as key_file:
                key_file.write(key)
            return key

    def encrypt(self, data: Dict[str, Any]) -> str:
        """
        Encrypts a dictionary into a token string.
        """
        json_str = json.dumps(data)
        encrypted_bytes = self.cipher_suite.encrypt(json_str.encode())
        return base64.urlsafe_b64encode(encrypted_bytes).decode()

    def decrypt(self, token: str) -> Dict[str, Any]:
        """
        Decrypts a token string back into a dictionary.
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(token.encode())
            decrypted_bytes = self.cipher_suite.decrypt(encrypted_bytes)
            return json.loads(decrypted_bytes.decode())
        except Exception as e:
            print(f"Decryption error: {e}")
            raise ValueError("Invalid token")

crypto_service = CryptoService()
