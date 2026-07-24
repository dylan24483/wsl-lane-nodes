"""Durable, monotonic per-lane RP2040 identity-capability evidence.

The legacy Rev-C escape is intentionally one-way during normal operation.
Once a lane has emitted any modern identity-capability evidence, a daemon
restart must not make that lane eligible for the legacy/no-identity path.

State is replaced atomically, the new file is fsynced before replacement, and
the parent directory is fsynced after replacement.  There is deliberately no
programmatic clear operation.  An operator who has physically verified a
legacy-board replacement may stop the service and remove the lane's state file;
the next startup creates a fresh, false record.  Malformed or unreadable
existing state is never interpreted as false.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager


SCHEMA_VERSION = 1
STATE_KEYS = frozenset((
    "schema_version", "lane_id", "identity_capable", "generation",
))
# Strong references keep acquired hardware leases alive until explicit complete
# teardown or process exit, including when BoardController construction fails
# after opening part of the hardware stack.
_PROCESS_OWNER_LEASES = set()
_PROCESS_OWNER_LEASES_LOCK = threading.Lock()


class IdentityEvidenceError(RuntimeError):
    """Durable identity evidence could not be trusted or committed."""


class ControllerOwnerLeaseError(IdentityEvidenceError):
    """Another process owns this lane's physical controller hardware."""


class ControllerOwnerLease:
    """Nonblocking, crash-released lifetime ownership of one lane's hardware.

    The short ``IdentityEvidenceStore`` lock serializes individual state-file
    updates.  This separate lease stays locked for the entire controller
    object's/process's lifetime, preventing a second daemon from caching legacy
    authorization and later driving the same lane after a peer closes the
    one-way identity latch.  The OS releases the advisory byte lock on process
    death; ``release`` exists for tests and complete object teardown only.
    """

    def __init__(self, directory, lane_id):
        if type(lane_id) is not int or not 1 <= lane_id <= 32:
            raise ValueError("lane_id must be an integer in 1..32")
        if not isinstance(directory, str) or not directory:
            raise ValueError("identity-state directory must be non-empty")
        self.directory = os.path.abspath(directory)
        self.lane_id = lane_id
        self.path = os.path.join(
            self.directory, f"controller-owner-lane-{lane_id}.lock")
        self._lock = threading.Lock()
        self._handle = None

    def acquire(self):
        """Acquire immediately or fail; never wait behind another controller."""
        with self._lock:
            if self._handle is not None:
                return self
            handle = None
            try:
                os.makedirs(self.directory, mode=0o750, exist_ok=True)
                handle = open(self.path, "a+b")
                try:
                    os.fchmod(handle.fileno(), 0o640)
                except (AttributeError, OSError):
                    pass
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(
                        handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception as exc:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
                raise ControllerOwnerLeaseError(
                    f"lane {self.lane_id} controller hardware is already "
                    f"owned or its owner lease cannot be acquired: "
                    f"{type(exc).__name__}: {exc}") from exc
            self._handle = handle
            with _PROCESS_OWNER_LEASES_LOCK:
                _PROCESS_OWNER_LEASES.add(self)
            return self

    def release(self):
        """Release after complete object teardown; normal process exit is enough."""
        with self._lock:
            handle = self._handle
            if handle is None:
                return
            self._handle = None
            try:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
            finally:
                with _PROCESS_OWNER_LEASES_LOCK:
                    _PROCESS_OWNER_LEASES.discard(self)

    @property
    def acquired(self):
        with self._lock:
            return self._handle is not None

def _fsync_parent(directory):
    """Fsync a directory on POSIX; tolerate the unsupported Windows test case."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        if os.name == "nt":
            return
        raise IdentityEvidenceError(
            f"cannot open identity-state directory for fsync: {exc}") from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        if os.name != "nt":
            raise IdentityEvidenceError(
                f"cannot fsync identity-state directory: {exc}") from exc
    finally:
        os.close(fd)


class IdentityEvidenceStore:
    """One crash-safe, monotonic identity-capability record for one lane."""

    def __init__(self, directory, lane_id):
        if type(lane_id) is not int or not 1 <= lane_id <= 32:
            raise ValueError("lane_id must be an integer in 1..32")
        if not isinstance(directory, str) or not directory:
            raise ValueError("identity-state directory must be non-empty")
        self.directory = os.path.abspath(directory)
        self.lane_id = lane_id
        self.path = os.path.join(
            self.directory, f"identity-capability-lane-{lane_id}.json")
        self.lock_path = self.path + ".lock"
        self._lock = threading.Lock()
        self._state = None

    @contextmanager
    def _process_lock(self):
        """Crash-released cross-process serialization for read/modify/write."""
        os.makedirs(self.directory, mode=0o750, exist_ok=True)
        handle = None
        try:
            handle = open(self.lock_path, "a+b")
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        except IdentityEvidenceError:
            raise
        except Exception as exc:
            raise IdentityEvidenceError(
                f"cannot lock identity state for lane {self.lane_id}: "
                f"{type(exc).__name__}: {exc}") from exc
        finally:
            if handle is not None:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(
                            handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                handle.close()

    @staticmethod
    def _validate(raw, lane_id):
        if not isinstance(raw, dict) or set(raw) != STATE_KEYS:
            raise IdentityEvidenceError(
                "identity-state record has an invalid schema")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise IdentityEvidenceError(
                "identity-state record has an unsupported schema version")
        if raw.get("lane_id") != lane_id:
            raise IdentityEvidenceError(
                "identity-state record belongs to a different lane")
        capable = raw.get("identity_capable")
        generation = raw.get("generation")
        if type(capable) is not bool:
            raise IdentityEvidenceError(
                "identity-state capability flag is not boolean")
        if type(generation) is not int or generation < 0:
            raise IdentityEvidenceError(
                "identity-state generation is invalid")
        if capable is not (generation > 0):
            raise IdentityEvidenceError(
                "identity-state capability/generation is inconsistent")
        return {
            "schema_version": SCHEMA_VERSION,
            "lane_id": lane_id,
            "identity_capable": capable,
            "generation": generation,
        }

    def _write(self, state):
        os.makedirs(self.directory, mode=0o750, exist_ok=True)
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".identity-capability-", suffix=".tmp",
                dir=self.directory)
            try:
                os.fchmod(fd, 0o640)
            except (AttributeError, OSError):
                # Windows tests do not expose POSIX file modes.
                pass
            encoded = (
                json.dumps(
                    state, sort_keys=True, separators=(",", ":"),
                    allow_nan=False)
                + "\n"
            ).encode("utf-8")
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            tmp_path = None
            _fsync_parent(self.directory)
        except IdentityEvidenceError:
            raise
        except Exception as exc:
            raise IdentityEvidenceError(
                f"cannot commit identity state for lane {self.lane_id}: "
                f"{type(exc).__name__}: {exc}") from exc
        finally:
            if fd is not None:
                os.close(fd)
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def load_or_initialize(self):
        """Load trusted state, or atomically create the first false record."""
        with self._lock:
            if self._state is not None:
                return dict(self._state)
            with self._process_lock():
                try:
                    with open(self.path, "r", encoding="utf-8") as handle:
                        raw = json.load(handle)
                except FileNotFoundError:
                    state = {
                        "schema_version": SCHEMA_VERSION,
                        "lane_id": self.lane_id,
                        "identity_capable": False,
                        "generation": 0,
                    }
                    self._write(state)
                    self._state = state
                    return dict(state)
                except Exception as exc:
                    raise IdentityEvidenceError(
                        f"existing identity state for lane {self.lane_id} is "
                        f"unreadable or corrupt: {type(exc).__name__}: {exc}") \
                        from exc
                self._state = self._validate(raw, self.lane_id)
                return dict(self._state)

    def mark_identity_capable(self):
        """Persist the sole normal transition, false -> true, and return state."""
        with self._lock:
            if self._state is None:
                raise IdentityEvidenceError(
                    "identity state must be loaded before it is updated")
            with self._process_lock():
                # Re-read under the inter-process lock. A delayed process that
                # cached generation 0 must merge a generation 1 written by a
                # peer, never replace it with stale false/old generation state.
                try:
                    with open(self.path, "r", encoding="utf-8") as handle:
                        current = self._validate(
                            json.load(handle), self.lane_id)
                except Exception as exc:
                    if isinstance(exc, IdentityEvidenceError):
                        raise
                    raise IdentityEvidenceError(
                        f"existing identity state for lane {self.lane_id} is "
                        f"unreadable, missing, or corrupt during update: "
                        f"{type(exc).__name__}: {exc}") from exc
                if current["identity_capable"]:
                    self._state = current
                    return dict(current)
                state = {
                    "schema_version": SCHEMA_VERSION,
                    "lane_id": self.lane_id,
                    "identity_capable": True,
                    "generation": current["generation"] + 1,
                }
                self._write(state)
                self._state = state
                return dict(state)
