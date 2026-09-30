"""Conservative read-only identity check for a retained Windows job PID.

Windows can reuse a finished worker's PID for an unrelated process. A live PID
is ignored only when its creation time proves it was born after the saved
terminal/paused checkpoint, or the OS identifies it as the exact system
conhost executable rather than a Python worker. Ambiguous evidence stays live.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import ntpath
from typing import Any

from tools import category_image_production as production


_STOPPED_STATUSES = frozenset({
    "paused_balance_exhausted", "paused_api_errors", "paused_request_budget",
    "paused_policy_circuit", "paused_resume_probe_failed", "paused_probe_failed",
    "awaiting_review", "completed", "completed_with_errors", "failed", "cancelled",
})


def _process_image_and_windows_directory(pid: int) -> tuple[str, str] | None:
    """Read the full image path and OS directory without mutable env lookup."""

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetWindowsDirectoryW.restype = wintypes.UINT
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            return None
        system_directory = ctypes.create_unicode_buffer(32768)
        count = kernel.GetWindowsDirectoryW(system_directory, len(system_directory))
        if not 0 < count < len(system_directory):
            return None
        return image.value, system_directory.value
    finally:
        kernel.CloseHandle(handle)


def _is_known_system_conhost(pid: int) -> bool:
    try:
        result = _process_image_and_windows_directory(pid)
        if result is None:
            return False
        image, windows_directory = result
        if not ntpath.isabs(image) or not ntpath.isabs(windows_directory):
            return False
        normalize = lambda value: ntpath.normcase(ntpath.normpath(value))
        allowed = {
            normalize(ntpath.join(windows_directory, folder, "conhost.exe"))
            for folder in ("System32", "SysWOW64")
        }
        return normalize(image) in allowed
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _process_creation_time_utc(pid: int) -> datetime | None:
    """GetProcessTimes with query-only rights; never terminates a process."""

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(system), ctypes.byref(user)):
            return None
        ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        if ticks <= 0:
            return None
        return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
    finally:
        kernel.CloseHandle(handle)


def _checkpoint_time_utc(job: dict[str, Any]) -> datetime | None:
    values = [job[key] for key in ("finished_at", "updated_at") if job.get(key)]
    if not values:
        return None
    parsed = []
    for value in values:
        if not isinstance(value, str):
            return None
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        parsed.append(stamp.astimezone(timezone.utc))
    # The later checkpoint is conservative if both timestamps are retained.
    return max(parsed)


def recorded_job_pid_is_running(pid: int, job: dict[str, Any]) -> bool:
    """Treat an unknown identity as live; discount only proven PID reuse."""

    if not production.pid_is_running(pid):
        return False
    if not isinstance(job, dict) or job.get("status") not in _STOPPED_STATUSES:
        return True
    if _is_known_system_conhost(pid):
        return False
    checkpoint = _checkpoint_time_utc(job)
    if checkpoint is None:
        return True
    try:
        created = _process_creation_time_utc(pid)
        if created is None or created.tzinfo is None or created.utcoffset() is None:
            return True
        return created.astimezone(timezone.utc) <= checkpoint
    except (OSError, ValueError, OverflowError, AttributeError):
        return True


__all__ = ["recorded_job_pid_is_running"]
