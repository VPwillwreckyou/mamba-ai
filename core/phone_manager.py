from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PhoneAction(str, Enum):
    """Types of phone communication actions."""
    CALL = "call"
    TEXT = "text"
    MESSAGE = "message"


@dataclass
class PhoneCommand:
    """Parsed phone command with resolved details."""
    action: PhoneAction
    recipient: str
    message: str | None = None
    is_default_number: bool = False
    raw_command: str = ""


class PhoneProvider(ABC):
    """Abstract interface for phone/VoIP/SMS providers.

    Each provider must implement actual call and text functionality.
    The PhoneManager validates commands before delegating to providers.
    """

    @abstractmethod
    async def make_call(self, phone_number: str, caller_id: str | None = None) -> dict[str, Any]:
        """Initiate a call to the specified phone number.

        Args:
            phone_number: The phone number to call.
            caller_id: Optional caller ID display name to use.

        Returns:
            dict with status and provider-specific details.
            Must include 'success' boolean key.
            May include 'caller_id_used' to report actual caller ID.
        """

    @abstractmethod
    async def send_text(self, phone_number: str, message: str, caller_id: str | None = None) -> dict[str, Any]:
        """Send a text message to the specified phone number.

        Args:
            phone_number: The phone number to text.
            message: The message content.
            caller_id: Optional caller ID display name to use.

        Returns:
            dict with status and provider-specific details.
            Must include 'success' boolean key.
            May include 'caller_id_used' to report actual caller ID.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and configured."""


class MockPhoneProvider(PhoneProvider):
    """Mock provider for testing when no real phone integration is available."""

    def __init__(self) -> None:
        self._call_log: list[dict[str, Any]] = []
        self._text_log: list[dict[str, Any]] = []

    async def make_call(self, phone_number: str, caller_id: str | None = None) -> dict[str, Any]:
        """Mock call initiation - logs the attempt."""
        self._call_log.append({
            "phone_number": phone_number,
            "caller_id": caller_id,
            "timestamp": self._get_timestamp(),
        })
        return {
            "success": True,
            "provider": "mock",
            "message": "Call initiated (mock provider)",
            "phone_number": self._redact_number(phone_number),
            "caller_id_used": caller_id,
        }

    async def send_text(self, phone_number: str, message: str, caller_id: str | None = None) -> dict[str, Any]:
        """Mock text sending - logs the attempt."""
        self._text_log.append({
            "phone_number": phone_number,
            "message": message,
            "caller_id": caller_id,
            "timestamp": self._get_timestamp(),
        })
        return {
            "success": True,
            "provider": "mock",
            "message": "Text sent (mock provider)",
            "phone_number": self._redact_number(phone_number),
            "caller_id_used": caller_id,
        }

    def is_available(self) -> bool:
        return True

    def _get_timestamp(self) -> str:
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _redact_number(self, number: str) -> str:
        """Redact phone number for logging."""
        if len(number) >= 4:
            return number[:2] + "***" + number[-2:]
        return "***"


class PhoneManager:
    """Manages phone communication with natural language command parsing.

    This manager:
    - Parses natural language phone commands
    - Resolves "me" references to configured default number
    - Validates phone numbers
    - Delegates to configured phone provider
    - Protects phone numbers in logs and output
    """

    # Patterns for natural language phone commands
    CALL_PATTERNS = [
        r"call\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)",
        r"call\s+me\s+on\s+my\s+phone",
        r"phone\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)",
        r"ring\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)",
        r"call\s+the\s+default\s+number",
        r"call\s+[\(\)\d\s\-]+",  # Matches phone numbers with various formats
    ]

    TEXT_PATTERNS = [
        r"text\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)",
        r"message\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)",
        r"send\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)\s+a\s+text",
        r"send\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)\s+a\s+message",
        r"text\s+the\s+default\s+number",
        r"text\s+[\(\)\d\s\-]+",  # Matches phone numbers with various formats
        r"send\s+(?:a\s+)?(?:text|message)\s+to\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)",
        r"send\s+(?:a\s+)?(?:text|message)\s+to\s+[\(\)\d\s\-]+",
    ]

    MESSAGE_WITH_CONTENT_PATTERNS = [
        r"(?:text|message|send\s+(?:a\s+)?(?:text|message)\s+to)\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)\s+(?:saying|with|:)\s+(.+)",
        r"(?:text|message|send\s+(?:a\s+)?(?:text|message)\s+to)\s+(me|my\s+number|my\s+phone|my\s+mobile|my\s+cell)\s+(.+)",
        r"(?:text|message|send\s+(?:a\s+)?(?:text|message)\s+to)\s+([\(\)\d\s\-]+)\s+(?:saying|with|:)\s+(.+)",
        r"(?:text|message|send\s+(?:a\s+)?(?:text|message)\s+to)\s+([\(\)\d\s\-]+)\s+(.+)",
    ]

    def __init__(self, *, default_phone_number: str | None = None, caller_id: str | None = None, provider: PhoneProvider | None = None) -> None:
        """
        Initialize the PhoneManager.

        Args:
            default_phone_number: Default phone number for "me" references.
                If None, reads from DEFAULT_PHONE_NUMBER environment variable.
            caller_id: Caller ID display name for outgoing calls.
                If None, reads from CALLER_ID environment variable.
            provider: Phone provider implementation. If None, uses MockPhoneProvider.
        """
        self._default_number = default_phone_number or os.getenv("DEFAULT_PHONE_NUMBER", "")
        self._caller_id = caller_id or os.getenv("CALLER_ID", "MAMBA AI")
        self._provider = provider or MockPhoneProvider()

    @property
    def default_phone_number(self) -> str:
        """Get the configured default phone number."""
        return self._default_number

    def set_default_phone_number(self, number: str) -> None:
        """Update the default phone number."""
        self._default_number = number

    @property
    def caller_id(self) -> str:
        """Get the configured caller ID display name."""
        return self._caller_id

    def set_caller_id(self, caller_id: str) -> None:
        """Update the caller ID display name."""
        self._caller_id = caller_id

    def parse_command(self, command: str) -> PhoneCommand | None:
        """
        Parse a natural language phone command.

        Args:
            command: Natural language command string.

        Returns:
            PhoneCommand if command is recognized, None otherwise.
        """
        command_lower = command.lower().strip()

        # Try message with content patterns first
        for pattern in self.MESSAGE_WITH_CONTENT_PATTERNS:
            match = re.search(pattern, command_lower, re.IGNORECASE)
            if match:
                recipient_ref = match.group(1).strip()
                # Re-run the pattern against the original command so the message
                # content keeps its original casing.
                original_match = re.search(pattern, command, re.IGNORECASE)
                message = (original_match.group(2) if original_match else match.group(2)).strip()
                # Extract phone number if recipient_ref is a phone number pattern
                if re.match(r"^[\(\)\d\s\-]+$", recipient_ref):
                    digits = re.sub(r"[^\d]", "", recipient_ref)
                    recipient = digits if digits else self._resolve_recipient(recipient_ref)
                    is_default = False
                else:
                    recipient = self._resolve_recipient(recipient_ref)
                    is_default = (recipient_ref.lower() in ["me", "my number", "my phone", "my mobile", "my cell"])
                if recipient:
                    return PhoneCommand(
                        action=PhoneAction.TEXT,
                        recipient=recipient,
                        message=message,
                        is_default_number=is_default,
                        raw_command=command,
                    )

        # Try call patterns
        for pattern in self.CALL_PATTERNS:
            match = re.search(pattern, command_lower, re.IGNORECASE)
            if match:
                # Some patterns may not have capture groups (e.g., "call me on my phone")
                if match.groups():
                    recipient_ref = match.group(1).strip()
                else:
                    # Extract phone number from the match for patterns without explicit capture group
                    matched_text = match.group(0)
                    # Remove "call " prefix and extract digits
                    digits = re.sub(r"[^\d]", "", matched_text)
                    if digits:
                        recipient_ref = digits
                    else:
                        recipient_ref = "me"
                recipient = self._resolve_recipient(recipient_ref)
                if recipient:
                    return PhoneCommand(
                        action=PhoneAction.CALL,
                        recipient=recipient,
                        is_default_number=(recipient_ref.lower() in ["me", "my number", "my phone", "my mobile", "my cell"]),
                        raw_command=command,
                    )

        # Try text patterns
        for pattern in self.TEXT_PATTERNS:
            match = re.search(pattern, command_lower, re.IGNORECASE)
            if match:
                # Some patterns may not have capture groups
                if match.groups():
                    recipient_ref = match.group(1).strip()
                else:
                    # Extract phone number from the match for patterns without explicit capture group
                    matched_text = match.group(0)
                    # Remove "text " prefix and extract digits
                    digits = re.sub(r"[^\d]", "", matched_text)
                    if digits:
                        recipient_ref = digits
                    else:
                        recipient_ref = "me"
                recipient = self._resolve_recipient(recipient_ref)
                if recipient:
                    return PhoneCommand(
                        action=PhoneAction.TEXT,
                        recipient=recipient,
                        is_default_number=(recipient_ref.lower() in ["me", "my number", "my phone", "my mobile", "my cell"]),
                        raw_command=command,
                    )

        return None

    def _resolve_recipient(self, recipient_ref: str) -> str | None:
        """
        Resolve a recipient reference to an actual phone number.

        Args:
            recipient_ref: Reference like "me", "my phone", or a phone number.

        Returns:
            Phone number string, or None if cannot be resolved.
        """
        recipient_lower = recipient_ref.lower()

        # Check for "me" references
        if recipient_lower in ["me", "my number", "my phone", "my mobile", "my cell", "the default number"]:
            if self._default_number:
                return self._default_number
            return None

        # Check if it's a phone number (extract digits)
        digits = re.sub(r"[^\d]", "", recipient_ref)
        if len(digits) >= 7:  # Minimum reasonable phone number length
            return digits

        return None

    def validate_phone_number(self, phone_number: str) -> bool:
        """
        Validate a phone number format.

        Args:
            phone_number: Phone number string.

        Returns:
            True if valid format, False otherwise.
        """
        digits = re.sub(r"[^\d]", "", phone_number)
        return len(digits) >= 7 and len(digits) <= 15

    async def execute_command(self, command: PhoneCommand) -> dict[str, Any]:
        """
        Execute a parsed phone command.

        Args:
            command: Parsed PhoneCommand.

        Returns:
            dict with execution result including 'success' boolean.
        """
        if not self._provider.is_available():
            return {
                "success": False,
                "error": "Phone provider not available",
                "action": command.action.value,
            }

        # Validate phone number
        if not self.validate_phone_number(command.recipient):
            return {
                "success": False,
                "error": f"Invalid phone number: {self._redact_number(command.recipient)}",
                "action": command.action.value,
            }

        try:
            if command.action == PhoneAction.CALL:
                result = await self._provider.make_call(command.recipient, caller_id=self._caller_id)
            elif command.action in [PhoneAction.TEXT, PhoneAction.MESSAGE]:
                if not command.message:
                    return {
                        "success": False,
                        "error": "No message content provided",
                        "action": command.action.value,
                    }
                result = await self._provider.send_text(command.recipient, command.message, caller_id=self._caller_id)
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {command.action.value}",
                    "action": command.action.value,
                }

            # Add redacted phone number and caller ID to result
            result["phone_number"] = self._redact_number(command.recipient)
            result["caller_id_configured"] = self._caller_id
            result["action"] = command.action.value
            result["is_default_number"] = command.is_default_number

            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "action": command.action.value,
            }

    def _redact_number(self, number: str) -> str:
        """
        Redact phone number for safe logging/display.

        Args:
            number: Full phone number.

        Returns:
            Redacted phone number (e.g., "05***85").
        """
        digits = re.sub(r"[^\d]", "", number)
        if len(digits) >= 4:
            return digits[:2] + "***" + digits[-2:]
        return "***"

    def is_phone_command(self, command: str) -> bool:
        """
        Check if a command is a phone-related command.

        Args:
            command: Command string to check.

        Returns:
            True if command appears to be phone-related.
        """
        return self.parse_command(command) is not None
