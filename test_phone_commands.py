#!/usr/bin/env python
"""Test script for phone command parsing."""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from core.phone_manager import PhoneManager


def test_phone_commands():
    """Test various natural language phone command variations."""
    
    # Initialize PhoneManager with default number
    default_number = os.getenv("DEFAULT_PHONE_NUMBER", "055190685")
    phone_manager = PhoneManager(default_phone_number=default_number)
    
    print(f"Default phone number: {phone_manager.default_phone_number}")
    print(f"Redacted: {phone_manager._redact_number(default_number)}")
    print("-" * 60)
    
    # Test commands
    test_commands = [
        # Call commands with "me"
        "Call me",
        "Call my number",
        "Call my phone",
        "Call me on my phone",
        "Phone me",
        "Ring me",
        "Call the default number",
        
        # Text commands with "me"
        "Text me",
        "Message me",
        "Send me a text",
        "Send me a message",
        "Text the default number",
        
        # Commands with specific phone number
        "Call 055190685",
        "Text 055190685",
        "Call (055) 190-685",
        
        # Message with content
        "Text me saying I'll be home in 20 minutes.",
        "Send me a message saying Meeting at 3pm",
        "Message me with: Don't forget the groceries",
        "Send a text to me saying Call me back",
        
        # Edge cases
        "Call my mobile",
        "Text my cell",
        "Ring my phone",
    ]
    
    results = []
    
    for command in test_commands:
        parsed = phone_manager.parse_command(command)
        if parsed:
            results.append({
                "command": command,
                "action": parsed.action.value,
                "recipient": parsed.recipient,
                "redacted": phone_manager._redact_number(parsed.recipient),
                "is_default": parsed.is_default_number,
                "message": parsed.message,
                "success": True
            })
        else:
            results.append({
                "command": command,
                "action": None,
                "recipient": None,
                "redacted": None,
                "is_default": None,
                "message": None,
                "success": False
            })
    
    # Print results
    print("\nTest Results:")
    print("=" * 80)
    
    for i, result in enumerate(results, 1):
        print(f"\n{i}. Command: \"{result['command']}\"")
        if result['success']:
            print(f"   [OK] Action: {result['action']}")
            print(f"   [OK] Recipient: {result['recipient']}")
            print(f"   [OK] Redacted: {result['redacted']}")
            print(f"   [OK] Is Default: {result['is_default']}")
            if result['message']:
                print(f"   [OK] Message: {result['message']}")
        else:
            print("   [FAIL] Failed to parse")
    
    # Summary
    print("\n" + "=" * 80)
    print(f"Total commands tested: {len(results)}")
    successful = sum(1 for r in results if r['success'])
    print(f"Successfully parsed: {successful}")
    print(f"Failed to parse: {len(results) - successful}")
    
    # Verify "me" resolves to default number
    me_commands = [r for r in results if r['success'] and r['is_default'] == True]
    print(f"\nCommands resolving to default number: {len(me_commands)}")
    
    # Verify specific number commands
    specific_commands = [r for r in results if r['success'] and r['is_default'] == False]
    print(f"Commands with specific numbers: {len(specific_commands)}")
    
    # Check if all "me" commands resolved correctly
    me_test_commands = [
        "Call me", "Call my number", "Call my phone", "Call me on my phone",
        "Phone me", "Ring me", "Text me", "Message me", "Send me a text",
        "Send me a message"
    ]
    
    print("\nVerifying 'me' resolution:")
    all_correct = True
    for cmd in me_test_commands:
        result = phone_manager.parse_command(cmd)
        if result and result.recipient == default_number:
            print(f"   [OK] \"{cmd}\" -> {phone_manager._redact_number(default_number)}")
        else:
            print(f"   [FAIL] \"{cmd}\" -> FAILED")
            all_correct = False
    
    if all_correct:
        print("\n[OK] All 'me' commands resolved correctly to default number")
    else:
        print("\n[FAIL] Some 'me' commands failed to resolve")

    assert all(result["success"] for result in results)


if __name__ == "__main__":
    test_phone_commands()
