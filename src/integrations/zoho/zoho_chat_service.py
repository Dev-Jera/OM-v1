import requests
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ZohoChatService:
    """
    Integration layer for Zoho Chat APIs (SalesIQ, Desk, or CRM).
    This class is reusable and can be mocked for testing.
    """
    def __init__(self, api_base_url: str, access_token: str, org_id: Optional[str] = None):
        self.api_base_url = api_base_url.rstrip("/")
        self.access_token = access_token
        self.org_id = org_id

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json",
        }
        if self.org_id:
            headers["orgId"] = self.org_id
        return headers

    def send_message(self, chat_id: str, message: str, sender: str = "bot") -> Dict[str, Any]:
        """
        Send a message to a Zoho chat session.
        """
        url = f"{self.api_base_url}/chats/{chat_id}/messages"
        payload = {
            "message": message,
            "sender": sender,
        }
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to send message to Zoho chat: {e}")
            return {"success": False, "error": str(e)}

    def receive_messages(self, chat_id: str, since: Optional[str] = None) -> Dict[str, Any]:
        """
        Poll or fetch messages from a Zoho chat session.
        """
        url = f"{self.api_base_url}/chats/{chat_id}/messages"
        params = {"since": since} if since else {}
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to receive messages from Zoho chat: {e}")
            return {"success": False, "error": str(e)}

    def create_chat(self, visitor_id: str, initial_message: str) -> Dict[str, Any]:
        """
        Create a new chat session for a visitor/user.
        """
        url = f"{self.api_base_url}/chats"
        payload = {
            "visitor_id": visitor_id,
            "message": initial_message,
        }
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to create Zoho chat: {e}")
            return {"success": False, "error": str(e)}

    def mock_send_message(self, chat_id: str, message: str, sender: str = "bot") -> Dict[str, Any]:
        """
        Mock sending a message (for testing without hitting Zoho API).
        """
        logger.info(f"[MOCK] Sending message to chat {chat_id}: {message}")
        return {"success": True, "chat_id": chat_id, "message": message, "sender": sender}

    def mock_receive_messages(self, chat_id: str, since: Optional[str] = None) -> Dict[str, Any]:
        """
        Mock receiving messages (for testing without hitting Zoho API).
        """
        logger.info(f"[MOCK] Receiving messages for chat {chat_id} since {since}")
        return {"success": True, "chat_id": chat_id, "messages": []}

    def mock_create_chat(self, visitor_id: str, initial_message: str) -> Dict[str, Any]:
        """
        Mock creating a chat (for testing without hitting Zoho API).
        """
        logger.info(f"[MOCK] Creating chat for visitor {visitor_id} with message: {initial_message}")
        return {"success": True, "chat_id": "mock-chat-id", "visitor_id": visitor_id, "message": initial_message}

# Usage example (real or mock):
# zoho = ZohoChatService(api_base_url, access_token, org_id)
# zoho.send_message(chat_id, "Hello from bot!")
# zoho.mock_send_message(chat_id, "Hello from bot!")
