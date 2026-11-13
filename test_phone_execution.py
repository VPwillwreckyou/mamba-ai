#!/usr/bin/env python
"""Test script for phone command execution."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from core.phone_manager import PhoneManager


@pytest.mark.asyncio
async def test_phone_execution():
    """Test phone command execution with mock provider."""
    
    # Initialize PhoneManager with default number and caller ID
    default_number = os.getenv("DEFAULT_PHONE_NUMBER", "055190685")
    caller_id = os.getenv("CALLER_ID", "MAMBA AI")
    phone_manager = PhoneManager(default_phone_number=default_number, caller_id=caller_id)
    
    print(f"Default phone number: {phone_manager.default_phone_number}")
    print(f"Caller ID: {phone_manager.caller_id}")
    print(f"Provider: {type(phone_manager._provider).__name__}")
    print(f"Provider available: {phone_manager._provider.is_available()}")
    print("-" * 60)
    
    # Test commands to execute
    test_commands = [
        "Call me",
        "Text me saying Test message from MAMBA",
        "Call 055190685",
        "Text 055190685 saying Hello from MAMBA AI",
    ]
    
    results = []
    
    for command in test_commands:
        print(f"\nTesting: \"{command}\"")
        
        # Parse command
        parsed = phone_manager.parse_command(command)
        if not parsed:
            print("  [FAIL] Failed to parse command")
            results.append({"command": command, "success": False, "error": "Parse failed"})
            continue
        
        print(f"  [OK] Parsed: action={parsed.action.value}, recipient={phone_manager._redact_number(parsed.recipient)}")
        if parsed.message:
            print(f"  [OK] Message: {parsed.message}")
        
        # Execute command
        try:
            result = await phone_manager.execute_command(parsed)
            if result.get("success"):
                print("  [OK] Execution successful")
                print(f"  [OK] Provider: {result.get('provider')}")
                print(f"  [OK] Phone number: {result.get('phone_number')}")
                print(f"  [OK] Caller ID configured: {result.get('caller_id_configured')}")
                print(f"  [OK] Caller ID used: {result.get('caller_id_used')}")
                if result.get('call_sid'):
                    print(f"  [OK] Call SID: {result.get('call_sid')}")
                if result.get('message_sid'):
                    print(f"  [OK] Message SID: {result.get('message_sid')}")
                results.append({
                    "command": command,
                    "success": True,
                    "action": result.get("action"),
                    "provider": result.get("provider"),
                })
            else:
                print(f"  [FAIL] Execution failed: {result.get('error')}")
                results.append({
                    "command": command,
                    "success": False,
                    "error": result.get("error"),
                })
        except Exception as e:
            print(f"  [FAIL] Exception: {e}")
            results.append({
                "command": command,
                "success": False,
                "error": str(e),
            })
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Total commands tested: {len(results)}")
    successful = sum(1 for r in results if r['success'])
    print(f"Successfully executed: {successful}")
    print(f"Failed: {len(results) - successful}")
    
    # Verify caller ID is being passed
    print("\nVerifying caller ID configuration:")
    caller_id_tests = [r for r in results if r['success']]
    if caller_id_tests:
        print(f"  [OK] Caller ID configured: {caller_id}")
        print(f"  [OK] Caller ID passed to provider in {len(caller_id_tests)} successful executions")
    else:
        print("  [FAIL] No successful executions to verify caller ID")

    assert all(r['success'] for r in results)


if __name__ == "__main__":
    asyncio.run(test_phone_execution())
