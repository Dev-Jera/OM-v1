from src.integrations.zoho.zoho_chat_service import ZohoChatService

# Example usage for both real and mock modes


def test_real_zoho_chat():
    # Replace with your actual Zoho API details
    api_base_url = "https://salesiq.zoho.com/api/v2"  # Example base URL
    access_token = "YOUR_ZOHO_ACCESS_TOKEN"
    org_id = "YOUR_ORG_ID"  # Optional, if required by Zoho

    zoho = ZohoChatService(api_base_url, access_token, org_id)

    # Create a chat session
    create_resp = zoho.create_chat(visitor_id="test-visitor-123", initial_message="Hello, I need help!")
    print("Create chat response:", create_resp)

    chat_id = create_resp.get("chat_id")
    if not chat_id:
        print("Failed to create chat (or using mock)")
        return

    # Send a message
    send_resp = zoho.send_message(chat_id, "This is a test message from the bot.")
    print("Send message response:", send_resp)

    # Receive messages
    recv_resp = zoho.receive_messages(chat_id)
    print("Receive messages response:", recv_resp)


def test_mock_zoho_chat():
    zoho = ZohoChatService(api_base_url="mock", access_token="mock")

    # Mock create chat
    create_resp = zoho.mock_create_chat(visitor_id="test-visitor-123", initial_message="Hello, I need help!")
    print("[MOCK] Create chat response:", create_resp)

    chat_id = create_resp.get("chat_id")

    # Mock send message
    send_resp = zoho.mock_send_message(chat_id, "This is a test message from the bot.")
    print("[MOCK] Send message response:", send_resp)

    # Mock receive messages
    recv_resp = zoho.mock_receive_messages(chat_id)
    print("[MOCK] Receive messages response:", recv_resp)


if __name__ == "__main__":
    print("--- Testing Zoho Chat Integration (Mock) ---")
    test_mock_zoho_chat()
    print("--- Testing Zoho Chat Integration (Real) ---")
    # Uncomment the next line and fill in your credentials to test real API
    # test_real_zoho_chat()
