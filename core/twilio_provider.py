"""Twilio provider implementation for real phone calls and SMS.

To use this provider, you need:
1. A Twilio account (https://www.twilio.com)
2. Account SID and Auth Token from Twilio console
3. A Twilio phone number (purchased from Twilio)
4. Environment variables:
   - TWILIO_ACCOUNT_SID
   - TWILIO_AUTH_TOKEN
   - TWILIO_PHONE_NUMBER

Install dependency:
    pip install twilio

Example configuration in .env:
    TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_PHONE_NUMBER=+1234567890
"""

from __future__ import annotations

import os
import re
from typing import Any

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    Client = None  # type: ignore
    TwilioRestException = None  # type: ignore

from core.phone_manager import PhoneProvider


class TwilioProvider(PhoneProvider):
    """Twilio-based phone provider for real calls and SMS."""

    def __init__(self) -> None:
        """Initialize Twilio provider with credentials from environment."""
        if not TWILIO_AVAILABLE:
            raise ImportError(
                "Twilio library not installed. Install with: pip install twilio"
            )

        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self._twilio_number = os.getenv("TWILIO_PHONE_NUMBER", "")

        if not account_sid or not auth_token:
            raise ValueError(
                "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in environment"
            )

        if not self._twilio_number:
            raise ValueError(
                "TWILIO_PHONE_NUMBER must be set in environment"
            )

        self._client = Client(account_sid, auth_token)

    async def make_call(self, phone_number: str, caller_id: str | None = None) -> dict[str, Any]:
        """Initiate a call using Twilio.

        Args:
            phone_number: The phone number to call (E.164 format recommended).
            caller_id: Optional caller ID name (Twilio uses the Twilio phone number as caller ID).

        Returns:
            dict with call status and details.
        """
        try:
            # Format phone number to E.164 if not already
            formatted_number = self._format_phone_number(phone_number)

            # Create the call
            call = self._client.calls.create(
                to=formatted_number,
                from_=self._twilio_number,
                twiml=(
                    "<Response><Say>Hello, this is MAMBA AI. "
                    "You asked me to call you.</Say></Response>"
                ),
            )

            return {
                "success": True,
                "provider": "twilio",
                "message": "Call initiated via Twilio",
                "phone_number": self._redact_number(phone_number),
                "caller_id_used": self._twilio_number,  # Twilio uses the purchased number
                "call_sid": call.sid,
                "call_status": call.status,
            }

        except TwilioRestException as e:
            return {
                "success": False,
                "provider": "twilio",
                "error": f"Twilio error: {e.msg}",
                "error_code": e.code,
                "phone_number": self._redact_number(phone_number),
            }
        except Exception as e:
            return {
                "success": False,
                "provider": "twilio",
                "error": str(e),
                "phone_number": self._redact_number(phone_number),
            }

    async def send_text(self, phone_number: str, message: str, caller_id: str | None = None) -> dict[str, Any]:
        """Send an SMS message using Twilio.

        Args:
            phone_number: The phone number to text (E.164 format recommended).
            message: The message content.
            caller_id: Optional caller ID name (Twilio uses the Twilio phone number as sender).

        Returns:
            dict with message status and details.
        """
        try:
            # Format phone number to E.164 if not already
            formatted_number = self._format_phone_number(phone_number)

            # Send the message
            msg = self._client.messages.create(
                body=message,
                from_=self._twilio_number,
                to=formatted_number
            )

            return {
                "success": True,
                "provider": "twilio",
                "message": "SMS sent via Twilio",
                "phone_number": self._redact_number(phone_number),
                "caller_id_used": self._twilio_number,
                "message_sid": msg.sid,
                "message_status": msg.status,
            }

        except TwilioRestException as e:
            return {
                "success": False,
                "provider": "twilio",
                "error": f"Twilio error: {e.msg}",
                "error_code": e.code,
                "phone_number": self._redact_number(phone_number),
            }
        except Exception as e:
            return {
                "success": False,
                "provider": "twilio",
                "error": str(e),
                "phone_number": self._redact_number(phone_number),
            }

    def is_available(self) -> bool:
        """Check if Twilio provider is configured and available."""
        return (
            TWILIO_AVAILABLE
            and bool(os.getenv("TWILIO_ACCOUNT_SID"))
            and bool(os.getenv("TWILIO_AUTH_TOKEN"))
            and bool(os.getenv("TWILIO_PHONE_NUMBER"))
        )

    def _format_phone_number(self, number: str) -> str:
        """Format phone number to E.164 format.

        Args:
            number: Phone number in any format.

        Returns:
            Phone number in E.164 format (e.g., +1234567890).
        """
        # Extract digits
        digits = re.sub(r"[^\d]", "", number)

        if len(digits) == 9 and digits.startswith("0"):
            return "+374" + digits[1:]
        if len(digits) == 10:
            return "+1" + digits
        if len(digits) > 10 and not digits.startswith("0"):
            return "+" + digits

        # Default: just add + prefix
        return "+" + digits

    def _redact_number(self, number: str) -> str:
        """Redact phone number for safe logging/display."""
        digits = re.sub(r"[^\d]", "", number)
        if len(digits) >= 4:
            return digits[:2] + "***" + digits[-2:]
        return "***"
