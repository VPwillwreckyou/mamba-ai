from __future__ import annotations

from coding.terminal import Terminal
from core.autonomy_manager import AutonomyLevel, AutonomyManager
from core.permission_manager import PermissionLevel, PermissionManager
from core.security_manager import SecurityManager
from core.verification_engine import VerificationEngine


def test_security_manager_emergency_stop():
    sm = SecurityManager()
    assert sm.is_allowed() is True
    sm.emergency_stop()
    assert sm.is_emergency_stop_active is True
    assert sm.is_access_revoked is True
    assert sm.is_allowed() is False


def test_security_manager_access_revoke():
    sm = SecurityManager()
    sm.revoke_access()
    assert sm.is_access_revoked is True
    assert sm.is_allowed() is False


def test_security_manager_restore_access():
    sm = SecurityManager()
    sm.revoke_access()
    sm.restore_access()
    assert sm.is_access_revoked is False
    assert sm.is_allowed() is True


def test_security_manager_sanitize_logging():
    sm = SecurityManager()
    dirty = "api_key=ABCDEFG password=secret token=12345"
    clean = sm.sanitize_for_logging(dirty)
    assert "***REDACTED***" in clean
    assert "ABCDEFG" not in clean


def test_permission_manager_default_policy():
    pm = PermissionManager()
    assert pm.level_for("search") == PermissionLevel.SAFE
    assert pm.level_for("delete_file") == PermissionLevel.CONFIRM
    assert pm.level_for("git_force_push") == PermissionLevel.RESTRICTED
    assert pm.may_execute("search") is True
    assert pm.may_execute("delete_file") is False
    assert pm.is_forbidden("git_force_push") is True


def test_permission_manager_authorize():
    pm = PermissionManager()
    assert pm.authorize("search") == "allowed"
    assert pm.authorize("delete_file") == "confirmation_required"
    assert pm.authorize("git_force_push") == "forbidden"


def test_terminal_detects_destructive_windows_command_aliases():
    destructive_commands = (
        "rd /s /q C:\\Users\\Public\\old",
        "erase /F C:\\Users\\Public\\old.txt",
        "powershell Clear-Disk -Number 1",
        "powershell Format-Volume -DriveLetter E",
        "powershell Remove-Partition -DiskNumber 1 -PartitionNumber 2",
    )

    for command in destructive_commands:
        assert Terminal.is_dangerous(command), command

    assert not Terminal.is_dangerous("python -m pytest -q")


def test_autonomy_manager_protected_actions():
    am = AutonomyManager(mode=AutonomyLevel.MAXIMUM)
    assert am.can_automate("read_file") is True
    assert am.can_automate("delete_file") is False
    assert am.supports_autonomous_execution() is True


def test_autonomy_manager_pause():
    am = AutonomyManager()
    am.stop()
    assert am.active is False
    assert am.can_automate("open_application") is False


def test_verification_engine_file_exists():
    ve = VerificationEngine()
    result = ve.verify_file_exists(__file__)
    assert result.passed is True
    assert result.action == "file_create"


def test_verification_engine_file_not_exists():
    ve = VerificationEngine()
    result = ve.verify_file_exists("does_not_exist_123.txt")
    assert result.passed is False
