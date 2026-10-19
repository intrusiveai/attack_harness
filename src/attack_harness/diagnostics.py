"""Bounded fatal diagnostics: allow known facts, never arbitrary exception text."""
import errno
import json
import os
import sys

from operator_contracts import ContractError


_REASONS = frozenset({
    "protocol-error", "closed", "deadline-exceeded", "user-request", "budget-limit",
    "host-shutdown", "operation-failed", "attempt-failed", "attempt-unknown",
    "model-generation-failed", "model-contract-failed", "model-compaction-failed",
    "model-compaction-contract-failed", "finalization-failed", "incomplete-execution",
    "work-after-finish", "invalid_arguments", "invalid_structure", "duplicate_json_key",
    "input_depth_exceeded", "invalid_base64", "direct_input_too_large",
})
_MESSAGES = frozenset({
    "contract message consistency check failed", "contract encoding limit exceeded",
    "contract exploration stopped", "attack harness runtime stopped",
    "FIFO initialization failed", "FIFO descriptor handoff failed", "FIFO send failed",
    "FIFO transport failed", "FIFO consumer deadline expired", "spool initialization failed",
    "spool send failed", "spool transport failed", "spool consumer deadline expired",
    "model usage unknown", "unsupported model codec",
})
_CLASSES = frozenset({"RuntimeStopped", "ContractError", "LoopStopped", "RuntimeError",
    "ValueError", "TypeError", "AssertionError", "ImportError", "ModuleNotFoundError",
    "OSError", "BrokenPipeError", "PermissionError", "FileNotFoundError", "TimeoutError",
    "ConnectionError", "ConnectionResetError", "UnicodeError", "UnicodeDecodeError"})


def close_after_failure(transport):
    """Cleanup must not replace an exception already in flight."""
    try:
        transport.close()
        return True
    except Exception:
        return False


def fatal_diagnostic(error, stage):
    wrapper = error
    seen = set()
    for _ in range(8):
        if error.__cause__ is None or id(error.__cause__) in seen:
            break
        seen.add(id(error))
        error = error.__cause__
    name = type(error).__name__
    result = {"stage": stage, "reason": "unexpected-error",
              "exception": name if name in _CLASSES else "Exception"}
    omissions = []
    if name not in _CLASSES:
        omissions.append("exception_class:untrusted")
    reason = getattr(error, "reason", None)
    if type(reason) is str and reason in _REASONS:
        result["reason"] = reason
    elif isinstance(error, OSError):
        result["reason"] = "io-error"
    elif isinstance(error, ImportError):
        result["reason"] = "import-error"
    elif isinstance(error, ContractError):
        result["reason"] = "contract-error"
    elif isinstance(error, RuntimeError):
        result["reason"] = "runtime-error"
    if reason is not None and (type(reason) is not str or reason not in _REASONS):
        omissions.append("reason:untrusted")
    wrapper_reason = getattr(wrapper, "reason", None)
    if wrapper is not error and type(wrapper_reason) is str and wrapper_reason in _REASONS:
        result["wrapper_reason"] = wrapper_reason
    # Never infer that arbitrary prose is safe merely because no secret regex matches.
    # errno text comes from the OS catalog, not exception.strerror or filenames.
    if isinstance(error, OSError) and type(error.errno) is int and error.errno in errno.errorcode:
        result["message"] = os.strerror(error.errno)
    elif type(error) in (ContractError, RuntimeError) and error.args and type(error.args[0]) is str and error.args[0] in _MESSAGES:
        result["message"] = error.args[0]
    else:
        result["message"] = "Exception message omitted: unrestricted or unavailable."
        omissions.append("message:untrusted-or-unavailable")
    if omissions:
        result["omissions"] = omissions
    return result


def emit_fatal(diagnostic):
    """One bounded line; a broken diagnostic sink cannot change the exit cause."""
    try:
        raw = json.dumps(diagnostic, ensure_ascii=True, separators=(",", ":"))
        if len(raw) > 1024:
            raw = '{"stage":"fatal","reason":"diagnostic-limit","message":"Diagnostic omitted: oversized."}'
        sys.stderr.write(raw + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def report_fatal(client, diagnostic):
    """Best effort only on a healthy admitted channel, before finish acceptance."""
    if client is None or client.stopped or client.finish_accepted or client.active:
        return
    if "engine.diagnostic_report" not in client.operations:
        return
    try:
        client.request("engine.diagnostic_report", {"diagnostic": {
            # The host retains a closed vocabulary for workflow diagnostics.
            # The detailed runtime stage/class/cause remain in bounded stderr.
            "source": "harness-local", "stage": "termination",
            "reason": "local_error", "message": diagnostic["exception"] + ": " + diagnostic["message"],
            "execution_occurred": "unknown", "resubmission_safe": False,
        }}, timeout_ms=1000)
    except Exception:
        pass
