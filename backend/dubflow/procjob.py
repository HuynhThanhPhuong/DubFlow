"""Reliable end of a process tree on Windows: one Job Object per engine / ffmpeg process.

`taskkill /T` can be refused (access denied) and then silently leaves children behind. A Job Object owns the process and
everything it starts: TerminateJobObject ends them all, its accounting says how many are still alive, and
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE ends them when this server exits, however it exits. Pure ctypes; nothing here is
imported or used on other platforms.
"""
from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

AVAILABLE = os.name == 'nt'
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectBasicAccountingInformation = 1
JobObjectExtendedLimitInformation = 9
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

if AVAILABLE:
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                                       'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]

    class ACCOUNTING(ctypes.Structure):
        _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                    ('ThisPeriodTotalUserTime', ctypes.c_longlong), ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
                    ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                    ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD),
                    ('szExeFile', ctypes.c_wchar * 260)]

    _k = ctypes.WinDLL('kernel32', use_last_error=True)
    _k.CreateJobObjectW.restype = wintypes.HANDLE
    _k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    _k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k.CloseHandle.argtypes = [wintypes.HANDLE]
    _k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _k.OpenProcess.restype = wintypes.HANDLE
    _k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


class ProcessJob:
    """A Job Object holding one process and its descendants (Windows)."""

    def __init__(self):
        if not AVAILABLE:
            raise OSError('Job Objects need Windows.')
        self.handle = _k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k.SetInformationJobObject(self.handle, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        """Put a just-started subprocess.Popen into the job; False when Windows refuses (it is then not tracked)."""
        try:
            ok = _k.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle)))  # noqa: SLF001
        except (AttributeError, TypeError, ValueError):
            return False
        if not ok:
            log.warning('AssignProcessToJobObject failed for pid %s: %s', process.pid, ctypes.WinError(ctypes.get_last_error()))
        return bool(ok)

    def active(self):
        """How many processes of the job are still running; None when it cannot be asked."""
        if not self.handle:
            return None
        info = ACCOUNTING()
        if not _k.QueryInformationJobObject(self.handle, JobObjectBasicAccountingInformation, ctypes.byref(info), ctypes.sizeof(info), None):
            return None
        return int(info.ActiveProcesses)

    def terminate(self, wait=5.0):
        """End every process of the job; True only once the job reports none alive."""
        if not self.handle:
            return True
        if not _k.TerminateJobObject(self.handle, 1):
            log.error('TerminateJobObject failed: %s', ctypes.WinError(ctypes.get_last_error()))
        deadline = time.monotonic() + wait
        while True:
            count = self.active()
            if count == 0:
                return True
            if count is None or time.monotonic() >= deadline:
                return False
            time.sleep(.05)

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            _k.CloseHandle(handle)


def descendants(pid):
    """PIDs of every process started (transitively) by pid, from a process snapshot (Windows); [] elsewhere."""
    if not AVAILABLE:
        return []
    snap = _k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    parents = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k.CloseHandle(snap)
    found, frontier = [], [int(pid)]
    while frontier:
        parent = frontier.pop()
        for child, owner in parents.items():
            if owner == parent and child not in found and child != pid:
                found.append(child)
                frontier.append(child)
    return found


def pid_alive(pid):
    if not AVAILABLE:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = _k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False  # gone (or not ours to see: treated as not alive)
    try:
        code = wintypes.DWORD()
        return bool(_k.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        _k.CloseHandle(handle)
