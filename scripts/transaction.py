#!/usr/bin/env python3
"""Preview-first, recoverable multi-file writes for litwiki.

See meta/TRANSACTIONS.md for the operator and durability contract.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator


SPEC_SCHEMA = "litwiki.transaction-spec.v1"
BUNDLE_SCHEMA = "litwiki.transaction.v1"
STATE_SCHEMA = "litwiki.transaction-state.v1"
RESULT_SCHEMA = "litwiki.transaction-result.v1"
RUNTIME_NAME = ".transactions"
PROTECTED_TOP = {".git", RUNTIME_NAME, ".cache"}
PROTECTED_EXACT = {"scripts/transaction.py"}
OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class TransactionError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise TransactionError("short write")
        view = view[written:]


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return b"".join(chunks)


def _regular_fd(path: Path) -> tuple[int, os.stat_result]:
    try:
        fd = os.open(path, os.O_RDONLY | NOFOLLOW)
    except OSError as exc:
        raise TransactionError(f"cannot open regular file no-follow: {path}: {exc}") from exc
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise TransactionError(f"not a regular file: {path}")
    return fd, info


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _mode(info: os.stat_result) -> int:
    return stat.S_IMODE(info.st_mode)


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


class TransactionEngine:
    def __init__(
        self,
        vault: Path,
        *,
        event_sink: Callable[[str], None] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        root = Path(vault).resolve(strict=True)
        if not root.is_dir():
            raise TransactionError(f"vault is not a directory: {root}")
        self.vault = root
        self.runtime = root / RUNTIME_NAME
        self.event_sink = event_sink
        self.failpoint = failpoint

    def _event(self, message: str) -> None:
        if self.event_sink:
            self.event_sink(message)

    def _hit(self, name: str) -> None:
        self._event(f"failpoint:{name}")
        if self.failpoint:
            self.failpoint(name)

    def _fsync_dir(self, path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        except OSError as exc:
            raise TransactionError(f"cannot open directory for fsync: {path}: {exc}") from exc
        try:
            os.fsync(fd)
            self._event(f"dir-fsync:{path}")
        finally:
            os.close(fd)

    def _fsync_file(self, path: Path) -> None:
        fd, _ = _regular_fd(path)
        try:
            os.fsync(fd)
            self._event(f"file-fsync:{path}")
        finally:
            os.close(fd)

    def _mkdir_durable(self, path: Path, *, exclusive: bool = False) -> None:
        current = _lstat(path)
        if current is not None:
            if exclusive:
                raise TransactionError(f"path already exists: {path}", 3)
            if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
                raise TransactionError(f"directory path is not a real directory: {path}")
            return
        try:
            os.mkdir(path, 0o700)
        except OSError as exc:
            raise TransactionError(f"cannot create directory: {path}: {exc}") from exc
        self._event(f"mkdir:{path}")
        self._fsync_dir(path.parent)

    def _ensure_tree(self, base: Path, relative_parent: PurePosixPath) -> Path:
        current = base
        for part in relative_parent.parts:
            current = current / part
            self._mkdir_durable(current)
        return current

    def _validate_operation_id(self, operation_id: object) -> str:
        if not isinstance(operation_id, str) or not OPERATION_ID_RE.fullmatch(operation_id):
            raise TransactionError("operation_id must be one conservative filename component")
        if operation_id in {".", ".."} or "/" in operation_id or "\\" in operation_id:
            raise TransactionError("invalid operation_id")
        return operation_id

    def _relative_target(self, raw: object) -> PurePosixPath:
        if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
            raise TransactionError(f"invalid target path: {raw!r}")
        relative = PurePosixPath(raw)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise TransactionError(f"target must be a normalized vault-relative path: {raw}")
        if str(relative) != raw:
            raise TransactionError(f"target path is not normalized: {raw}")
        if relative.parts[0] in PROTECTED_TOP or raw in PROTECTED_EXACT:
            raise TransactionError(f"protected transaction target: {raw}")
        candidate = self.vault
        for index, part in enumerate(relative.parts):
            candidate = candidate / part
            info = _lstat(candidate)
            if info is not None and stat.S_ISLNK(info.st_mode):
                raise TransactionError(f"symlink in target path: {candidate}")
            if index < len(relative.parts) - 1:
                if info is None or not stat.S_ISDIR(info.st_mode):
                    raise TransactionError(f"target parent is not an existing directory: {candidate}")
            elif info is not None and not stat.S_ISREG(info.st_mode):
                raise TransactionError(f"target is not a regular file: {candidate}")
        return relative

    def _target(self, relative: PurePosixPath) -> Path:
        return self.vault.joinpath(*relative.parts)

    def _path_is_within_vault(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self.vault)
            return True
        except ValueError:
            return False

    def _open_json(self, path: Path) -> tuple[dict, bytes, int, os.stat_result]:
        fd, info = _regular_fd(path)
        try:
            raw = _read_fd(fd)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TransactionError(f"invalid JSON: {path}: {exc}") from exc
            if not isinstance(value, dict):
                raise TransactionError(f"JSON root must be an object: {path}")
            return value, raw, fd, info
        except Exception:
            os.close(fd)
            raise

    def _copy_fd_to_new(self, source_fd: int, destination: Path, mode: int) -> str:
        try:
            out = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, mode)
        except OSError as exc:
            raise TransactionError(f"cannot exclusively create snapshot: {destination}: {exc}") from exc
        digest = hashlib.sha256()
        try:
            os.lseek(source_fd, 0, os.SEEK_SET)
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                _write_all(out, chunk)
            os.fchmod(out, mode)
            os.fsync(out)
            self._event(f"file-fsync:{destination}")
        finally:
            os.close(out)
            os.lseek(source_fd, 0, os.SEEK_SET)
        self._fsync_dir(destination.parent)
        return digest.hexdigest()

    def _copy_path_to_new(self, source: Path, destination: Path, mode: int, expected: str) -> None:
        fd, _ = _regular_fd(source)
        try:
            actual = self._copy_fd_to_new(fd, destination, mode)
        finally:
            os.close(fd)
        if actual != expected:
            raise TransactionError(f"snapshot hash mismatch for {source}: expected {expected}, got {actual}", 3)
        self._event(f"snapshot-verified:{destination}")

    def _hash_regular(self, path: Path) -> tuple[str, int]:
        fd, info = _regular_fd(path)
        try:
            digest = hashlib.sha256(_read_fd(fd)).hexdigest()
            return digest, _mode(info)
        finally:
            os.close(fd)

    def _fingerprint(self, path: Path) -> dict | None:
        info = _lstat(path)
        if info is None:
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise TransactionError(f"target is no longer a regular no-follow file: {path}", 3)
        digest, mode = self._hash_regular(path)
        return {"sha256": digest, "mode": mode}

    def _expected_original(self, write: dict) -> dict | None:
        if write["mode"] == "create":
            return None
        return {"sha256": write["expected_sha256"], "mode": write["original_mode"]}

    def _expected_new(self, write: dict) -> dict:
        return {"sha256": write["content_sha256"], "mode": write["new_mode"]}

    def _classify(self, write: dict) -> str:
        current = self._fingerprint(self._target(PurePosixPath(write["path"])))
        if current == self._expected_original(write):
            return "original"
        if current == self._expected_new(write):
            return "new"
        return "unexpected"

    def _atomic_json(self, path: Path, value: dict) -> None:
        data = _canonical_json(value)
        temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
        except OSError as exc:
            raise TransactionError(f"cannot create atomic JSON temporary: {temp}: {exc}") from exc
        try:
            _write_all(fd, data)
            os.fsync(fd)
            self._event(f"file-fsync:{temp}")
        finally:
            os.close(fd)
        os.replace(temp, path)
        self._event(f"replace:{temp}->{path}")
        self._fsync_file(path)
        self._fsync_dir(path.parent)

    def _read_json_file(self, path: Path) -> dict:
        value, raw, fd, _ = self._open_json(path)
        os.close(fd)
        if raw != _canonical_json(value):
            raise TransactionError(f"non-canonical journal JSON: {path}")
        return value

    def _validate_content_file(self, raw: object) -> tuple[Path, int, os.stat_result, str]:
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise TransactionError("content_file must be an absolute path")
        supplied = Path(raw)
        fd, info = _regular_fd(supplied)
        path = supplied.resolve(strict=True)
        if self._path_is_within_vault(path):
            os.close(fd)
            raise TransactionError(f"content_file must be outside the vault: {path}")
        digest = hashlib.sha256(_read_fd(fd)).hexdigest()
        return path, fd, info, digest

    def prepare(self, spec_path: Path, bundle_path: Path) -> dict:
        spec, _, spec_fd, spec_info = self._open_json(Path(spec_path))
        try:
            if set(spec) != {"schema", "operation_id", "writes"} or spec.get("schema") != SPEC_SCHEMA:
                raise TransactionError(f"spec must have schema {SPEC_SCHEMA} and exact top-level fields")
            operation_id = self._validate_operation_id(spec.get("operation_id"))
            items = spec.get("writes")
            if not isinstance(items, list) or not items:
                raise TransactionError("spec writes must be a non-empty list")
            seen_targets: set[str] = set()
            seen_sources: set[tuple[int, int]] = {_identity(spec_info)}
            writes: list[dict] = []
            opened: list[int] = []
            try:
                for item in items:
                    if not isinstance(item, dict) or set(item) != {"path", "content_file"}:
                        raise TransactionError("each spec write needs exactly path and content_file")
                    relative = self._relative_target(item["path"])
                    target_name = str(relative)
                    if target_name in seen_targets:
                        raise TransactionError(f"duplicate target path: {target_name}")
                    seen_targets.add(target_name)
                    source, source_fd, source_info, content_hash = self._validate_content_file(item["content_file"])
                    opened.append(source_fd)
                    source_identity = _identity(source_info)
                    if source_identity in seen_sources:
                        raise TransactionError(f"spec/content files must have distinct identities: {source}")
                    seen_sources.add(source_identity)
                    target = self._target(relative)
                    original = self._fingerprint(target)
                    mode = "create" if original is None else "replace"
                    writes.append(
                        {
                            "path": target_name,
                            "mode": mode,
                            "expected_sha256": None if original is None else original["sha256"],
                            "original_mode": None if original is None else original["mode"],
                            "new_mode": 0o644 if original is None else original["mode"],
                            "content_file": str(source),
                            "content_sha256": content_hash,
                        }
                    )
            finally:
                for fd in opened:
                    os.close(fd)

            bundle = {
                "schema": BUNDLE_SCHEMA,
                "operation_id": operation_id,
                "vault": str(self.vault),
                "writes": writes,
            }
            output = Path(bundle_path)
            if not output.is_absolute():
                output = Path.cwd() / output
            parent = output.parent.resolve(strict=True)
            output = parent / output.name
            if self._path_is_within_vault(output):
                raise TransactionError(f"bundle must be outside the vault: {output}")
            data = _canonical_json(bundle)
            try:
                out = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
            except OSError as exc:
                raise TransactionError(f"bundle must not already exist and must be no-follow: {output}: {exc}") from exc
            try:
                _write_all(out, data)
                os.fsync(out)
                self._event(f"file-fsync:{output}")
            finally:
                os.close(out)
            self._fsync_dir(parent)
            return {"operation_id": operation_id, "bundle": str(output), "bundle_sha256": _sha256_bytes(data)}
        finally:
            os.close(spec_fd)

    def _load_bundle(
        self,
        bundle_path: Path,
        *,
        check_live: bool,
        check_content: bool = True,
    ) -> tuple[dict, bytes]:
        bundle, raw, fd, _ = self._open_json(Path(bundle_path))
        os.close(fd)
        if raw != _canonical_json(bundle):
            raise TransactionError("bundle must use canonical JSON bytes")
        if set(bundle) != {"schema", "operation_id", "vault", "writes"}:
            raise TransactionError("bundle has unexpected top-level fields")
        if bundle.get("schema") != BUNDLE_SCHEMA or bundle.get("vault") != str(self.vault):
            raise TransactionError("bundle schema or resolved vault does not match")
        self._validate_operation_id(bundle.get("operation_id"))
        writes = bundle.get("writes")
        if not isinstance(writes, list) or not writes:
            raise TransactionError("bundle writes must be a non-empty list")
        seen: set[str] = set()
        for write in writes:
            required = {
                "path", "mode", "expected_sha256", "original_mode", "new_mode",
                "content_file", "content_sha256",
            }
            if not isinstance(write, dict) or set(write) != required:
                raise TransactionError("bundle write has unexpected fields")
            relative = self._relative_target(write["path"])
            if str(relative) in seen:
                raise TransactionError(f"duplicate bundle target: {relative}")
            seen.add(str(relative))
            if write["mode"] not in {"create", "replace"}:
                raise TransactionError(f"invalid write mode: {write['mode']}")
            if write["mode"] == "create":
                if write["expected_sha256"] is not None or write["original_mode"] is not None:
                    raise TransactionError("create write must have null original fingerprint")
            else:
                if not isinstance(write["expected_sha256"], str) or not isinstance(write["original_mode"], int):
                    raise TransactionError("replace write needs an original fingerprint")
            if not isinstance(write["new_mode"], int) or not isinstance(write["content_sha256"], str):
                raise TransactionError("write needs new mode and content hash")
            if check_content:
                source, source_fd, _, digest = self._validate_content_file(write["content_file"])
                os.close(source_fd)
                if str(source) != write["content_file"] or digest != write["content_sha256"]:
                    raise TransactionError(f"draft content changed: {source}", 3)
            if check_live and self._fingerprint(self._target(relative)) != self._expected_original(write):
                raise TransactionError(f"target precondition changed: {relative}", 3)
        return bundle, raw

    def inspect(self, bundle_path: Path) -> dict:
        bundle, raw = self._load_bundle(bundle_path, check_live=True)
        approval = _sha256_bytes(b"litwiki-apply-v1\0" + str(self.vault).encode() + b"\0" + raw)
        return {
            "action": "apply",
            "operation_id": bundle["operation_id"],
            "vault": str(self.vault),
            "bundle_sha256": _sha256_bytes(raw),
            "approval_sha256": approval,
            "writes": [
                {
                    "path": write["path"],
                    "absolute_path": str(self._target(PurePosixPath(write["path"]))),
                    "mode": write["mode"],
                    "expected_sha256": write["expected_sha256"],
                    "content_sha256": write["content_sha256"],
                }
                for write in bundle["writes"]
            ],
        }

    def _ensure_runtime(self) -> None:
        self._mkdir_durable(self.runtime)

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        self._ensure_runtime()
        lock_path = self.runtime / "lock"
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | NOFOLLOW, 0o600)
        except OSError as exc:
            raise TransactionError(f"cannot open transaction lock: {exc}", 5) from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise TransactionError("transaction lock is not a regular file", 5)
            os.fsync(fd)
            self._fsync_dir(self.runtime)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TransactionError("another litwiki transaction holds the lock", 5) from exc
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _operation_dir(self, operation_id: str, *, must_exist: bool = True) -> Path:
        operation_id = self._validate_operation_id(operation_id)
        path = self.runtime / operation_id
        info = _lstat(path)
        if must_exist:
            if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise TransactionError(f"transaction journal not found or unsafe: {path}")
        elif info is not None:
            raise TransactionError(f"transaction journal already exists: {path}", 3)
        return path

    def _state(self, op_dir: Path) -> dict:
        state_value = self._read_json_file(op_dir / "state.json")
        if state_value.get("schema") != STATE_SCHEMA:
            raise TransactionError(f"invalid transaction state: {op_dir}")
        return state_value

    def _write_state(self, op_dir: Path, state_value: dict) -> None:
        self._atomic_json(op_dir / "state.json", state_value)
        self._event(f"state:{state_value['phase']}")

    def _journal_bundle(self, bundle_path: Path, op_dir: Path, expected_hash: str) -> None:
        fd, _ = _regular_fd(bundle_path)
        try:
            actual = self._copy_fd_to_new(fd, op_dir / "bundle.json", 0o600)
        finally:
            os.close(fd)
        if actual != expected_hash:
            raise TransactionError("bundle changed while journaling", 3)

    def _snapshot_apply(self, bundle: dict, op_dir: Path) -> dict:
        staged = op_dir / "staged"
        originals = op_dir / "originals"
        self._mkdir_durable(staged)
        self._mkdir_durable(originals)
        state_writes: list[dict] = []
        for write in bundle["writes"]:
            relative = PurePosixPath(write["path"])
            self._ensure_tree(staged, relative.parent)
            source_fd, _ = _regular_fd(Path(write["content_file"]))
            try:
                staged_path = staged.joinpath(*relative.parts)
                actual = self._copy_fd_to_new(source_fd, staged_path, write["new_mode"])
            finally:
                os.close(source_fd)
            if actual != write["content_sha256"]:
                raise TransactionError(f"draft changed during snapshot: {write['content_file']}", 3)
            self._event(f"snapshot-verified:{staged_path}")
            if write["mode"] == "replace":
                self._ensure_tree(originals, relative.parent)
                target_fd, target_info = _regular_fd(self._target(relative))
                try:
                    original_path = originals.joinpath(*relative.parts)
                    original_hash = self._copy_fd_to_new(target_fd, original_path, _mode(target_info))
                finally:
                    os.close(target_fd)
                if original_hash != write["expected_sha256"] or _mode(target_info) != write["original_mode"]:
                    raise TransactionError(f"target changed during snapshot: {relative}", 3)
                self._event(f"snapshot-verified:{original_path}")
            state_writes.append(
                {
                    "path": write["path"],
                    "mode": write["mode"],
                    "original": self._expected_original(write),
                    "new": self._expected_new(write),
                    "completed": False,
                }
            )
        return {
            "schema": STATE_SCHEMA,
            "operation_id": bundle["operation_id"],
            "phase": "prepared",
            "recovery_direction": "original",
            "writes": state_writes,
        }

    def _install_one(self, op_dir: Path, write: dict) -> None:
        relative = PurePosixPath(write["path"])
        target = self._target(relative)
        staged = op_dir.joinpath("staged", *relative.parts)
        if self._classify(write) != "original":
            raise TransactionError(f"target changed immediately before apply: {relative}", 3)
        if self._fingerprint(staged) != self._expected_new(write):
            raise TransactionError(f"staged file changed: {staged}", 3)
        if write["mode"] == "create":
            try:
                os.link(staged, target, follow_symlinks=False)
            except OSError as exc:
                raise TransactionError(f"atomic create failed for {relative}: {exc}", 3) from exc
            self._event(f"link:{staged}->{target}")
            self._fsync_file(target)
            self._fsync_dir(staged.parent)
            self._fsync_dir(target.parent)
        else:
            os.replace(staged, target)
            self._event(f"replace:{staged}->{target}")
            self._fsync_file(target)
            self._fsync_dir(staged.parent)
            if target.parent != staged.parent:
                self._fsync_dir(target.parent)
        if self._fingerprint(target) != self._expected_new(write):
            raise TransactionError(f"live target verification failed: {relative}")
        self._event(f"live-installed:{relative}")
        self._hit(f"after-live:{relative}")

    def _copy_for_restore(self, source: Path, root: Path, relative: PurePosixPath, fingerprint: dict) -> Path:
        self._mkdir_durable(root)
        attempt = root / f"attempt-{uuid.uuid4().hex}"
        self._mkdir_durable(attempt)
        self._ensure_tree(attempt, relative.parent)
        destination = attempt.joinpath(*relative.parts)
        self._copy_path_to_new(source, destination, fingerprint["mode"], fingerprint["sha256"])
        return destination

    def _replace_from_snapshot(self, source: Path, target: Path, relative: PurePosixPath, fingerprint: dict, root: Path) -> None:
        staged = self._copy_for_restore(source, root, relative, fingerprint)
        os.replace(staged, target)
        self._event(f"replace:{staged}->{target}")
        self._fsync_file(target)
        self._fsync_dir(staged.parent)
        if target.parent != staged.parent:
            self._fsync_dir(target.parent)

    def _restore_original(self, op_dir: Path, bundle: dict, state_value: dict) -> None:
        archive_root = op_dir / "recovered-created"
        restore_root = op_dir / "restore-original"
        self._mkdir_durable(archive_root)
        self._mkdir_durable(restore_root)
        for write in reversed(bundle["writes"]):
            relative = PurePosixPath(write["path"])
            target = self._target(relative)
            classification = self._classify(write)
            if classification == "original":
                continue
            if classification != "new":
                raise TransactionError(f"cannot restore unexpected target: {relative}", 3)
            if write["mode"] == "create":
                attempt = archive_root / f"attempt-{uuid.uuid4().hex}"
                self._mkdir_durable(attempt)
                self._ensure_tree(attempt, relative.parent)
                archive = attempt.joinpath(*relative.parts)
                os.replace(target, archive)
                self._event(f"replace:{target}->{archive}")
                self._fsync_file(archive)
                self._fsync_dir(target.parent)
                self._fsync_dir(archive.parent)
            else:
                original = op_dir.joinpath("originals", *relative.parts)
                self._replace_from_snapshot(original, target, relative, self._expected_original(write), restore_root)
        for write in bundle["writes"]:
            if self._fingerprint(self._target(PurePosixPath(write["path"]))) != self._expected_original(write):
                raise TransactionError(f"original-state verification failed: {write['path']}")
        state_value["phase"] = "rolled-back"
        state_value["recovery_direction"] = "original"
        self._write_state(op_dir, state_value)

    def apply(self, bundle_path: Path, approval_sha256: str) -> dict:
        preview = self.inspect(bundle_path)
        if approval_sha256 != preview["approval_sha256"]:
            raise TransactionError("approval hash does not match inspected apply plan", 4)
        with self._lock():
            preview = self.inspect(bundle_path)
            if approval_sha256 != preview["approval_sha256"]:
                raise TransactionError("apply plan changed after approval", 4)
            bundle, raw = self._load_bundle(bundle_path, check_live=True)
            op_dir = self._operation_dir(bundle["operation_id"], must_exist=False)
            self._mkdir_durable(op_dir, exclusive=True)
            state_value: dict | None = None
            try:
                self._journal_bundle(Path(bundle_path), op_dir, _sha256_bytes(raw))
                state_value = self._snapshot_apply(bundle, op_dir)
                self._write_state(op_dir, state_value)
                self._hit("after-snapshots")
                state_value["phase"] = "applying"
                self._write_state(op_dir, state_value)
                for index, write in enumerate(bundle["writes"]):
                    self._install_one(op_dir, write)
                    state_value["writes"][index]["completed"] = True
                    self._write_state(op_dir, state_value)
                results = []
                for write in bundle["writes"]:
                    target = self._target(PurePosixPath(write["path"]))
                    actual = self._fingerprint(target)
                    if actual != self._expected_new(write):
                        raise TransactionError(f"final target mismatch: {write['path']}")
                    results.append({"path": write["path"], **actual})
                result = {
                    "schema": RESULT_SCHEMA,
                    "operation_id": bundle["operation_id"],
                    "bundle_sha256": _sha256_bytes(raw),
                    "targets": results,
                }
                self._atomic_json(op_dir / "result.json", result)
                state_value["phase"] = "applied"
                self._write_state(op_dir, state_value)
                return {
                    "operation_id": bundle["operation_id"],
                    "state": "applied",
                    "journal": str(op_dir),
                    "changed_paths": [str(self._target(PurePosixPath(w["path"]))) for w in bundle["writes"]],
                }
            except Exception as exc:
                if state_value is None:
                    state_value = {
                        "schema": STATE_SCHEMA,
                        "operation_id": bundle["operation_id"],
                        "phase": "rolled-back",
                        "recovery_direction": "original",
                        "writes": [],
                    }
                    with contextlib.suppress(Exception):
                        self._write_state(op_dir, state_value)
                    raise TransactionError(f"apply failed before live writes: {exc}") from exc
                state_value["phase"] = "recovery-required"
                state_value["recovery_direction"] = "original"
                with contextlib.suppress(Exception):
                    self._write_state(op_dir, state_value)
                try:
                    self._restore_original(op_dir, bundle, state_value)
                except Exception as recovery_exc:
                    raise TransactionError(
                        f"apply failed and automatic recovery is required: {exc}; recovery error: {recovery_exc}", 6
                    ) from exc
                raise TransactionError(f"apply failed; original state restored: {exc}", 6) from exc

    def _load_journal(self, operation_id: str) -> tuple[Path, dict, dict]:
        self._ensure_runtime()
        op_dir = self._operation_dir(operation_id)
        bundle, raw = self._load_bundle(op_dir / "bundle.json", check_live=False, check_content=False)
        state_value = self._state(op_dir)
        if bundle["operation_id"] != operation_id or state_value.get("operation_id") != operation_id:
            raise TransactionError("journal operation identity mismatch")
        return op_dir, bundle, state_value

    def _result(self, op_dir: Path, bundle: dict) -> dict:
        result = self._read_json_file(op_dir / "result.json")
        if set(result) != {"schema", "operation_id", "bundle_sha256", "targets"}:
            raise TransactionError("transaction result has unexpected fields")
        if result.get("schema") != RESULT_SCHEMA or result.get("operation_id") != bundle["operation_id"]:
            raise TransactionError("transaction result identity mismatch")
        if result.get("bundle_sha256") != _sha256_bytes(_canonical_json(bundle)):
            raise TransactionError("transaction result refers to a different bundle")
        expected_targets = [
            {"path": write["path"], **self._expected_new(write)}
            for write in bundle["writes"]
        ]
        if result.get("targets") != expected_targets:
            raise TransactionError("transaction result target fingerprints do not match the bundle")
        return result

    def _action_approval(
        self,
        action: str,
        operation_id: str,
        direction: str,
        bundle: dict,
        state_value: dict,
    ) -> dict:
        current = []
        for write in bundle["writes"]:
            target = self._target(PurePosixPath(write["path"]))
            current.append(
                {
                    "path": write["path"],
                    "absolute_path": str(target),
                    "fingerprint": self._fingerprint(target),
                }
            )
        payload = {
            "action": action,
            "operation_id": operation_id,
            "direction": direction,
            "vault": str(self.vault),
            "state": state_value["phase"],
            "bundle_sha256": _sha256_bytes(_canonical_json(bundle)),
            "current": current,
        }
        approval = _sha256_bytes(b"litwiki-action-v1\0" + _canonical_json(payload))
        return {**payload, "approval_sha256": approval}

    def rollback_plan(self, operation_id: str) -> dict:
        op_dir, bundle, state_value = self._load_journal(operation_id)
        if state_value["phase"] != "applied":
            raise TransactionError(f"rollback requires applied state, got {state_value['phase']}")
        self._result(op_dir, bundle)
        for write in bundle["writes"]:
            if self._classify(write) != "new":
                raise TransactionError(f"rollback refuses changed target: {write['path']}", 3)
            if write["mode"] == "replace":
                original = op_dir.joinpath("originals", *PurePosixPath(write["path"]).parts)
                if self._fingerprint(original) != self._expected_original(write):
                    raise TransactionError(f"rollback original snapshot missing or changed: {write['path']}")
        return self._action_approval("rollback", operation_id, "original", bundle, state_value)

    def _snapshot_applied_for_rollback(self, op_dir: Path, bundle: dict) -> Path:
        root = op_dir / "rollback-current"
        root_info = _lstat(root)
        if root_info is not None:
            if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
                raise TransactionError(f"rollback snapshot root is unsafe: {root}")
            for write in bundle["writes"]:
                snapshot = root.joinpath(*PurePosixPath(write["path"]).parts)
                if self._fingerprint(snapshot) != self._expected_new(write):
                    raise TransactionError(f"existing rollback snapshot is incomplete or changed: {write['path']}")
            self._event(f"rollback-snapshot-reused:{root}")
            return root

        attempt = op_dir / f"rollback-current-attempt-{uuid.uuid4().hex}"
        self._mkdir_durable(attempt, exclusive=True)
        for write in bundle["writes"]:
            relative = PurePosixPath(write["path"])
            self._ensure_tree(attempt, relative.parent)
            target = self._target(relative)
            self._copy_path_to_new(
                target,
                attempt.joinpath(*relative.parts),
                write["new_mode"],
                write["content_sha256"],
            )
        if _lstat(root) is not None:
            raise TransactionError(f"rollback snapshot appeared concurrently: {root}", 3)
        os.rename(attempt, root)
        self._event(f"rename-dir:{attempt}->{root}")
        self._fsync_dir(op_dir)
        return root

    def _restore_applied(self, op_dir: Path, bundle: dict, state_value: dict) -> None:
        snapshots = op_dir / "rollback-current"
        restore_root = op_dir / "restore-applied"
        self._mkdir_durable(restore_root)
        for write in bundle["writes"]:
            relative = PurePosixPath(write["path"])
            target = self._target(relative)
            classification = self._classify(write)
            if classification == "new":
                continue
            if classification not in {"original"}:
                raise TransactionError(f"cannot restore applied state over unexpected target: {relative}", 3)
            source = snapshots.joinpath(*relative.parts)
            if write["mode"] == "create":
                staged = self._copy_for_restore(source, restore_root, relative, self._expected_new(write))
                try:
                    os.link(staged, target, follow_symlinks=False)
                except OSError as exc:
                    raise TransactionError(f"cannot restore created applied target: {relative}: {exc}") from exc
                self._event(f"link:{staged}->{target}")
                self._fsync_file(target)
                self._fsync_dir(staged.parent)
                self._fsync_dir(target.parent)
            else:
                self._replace_from_snapshot(source, target, relative, self._expected_new(write), restore_root)
        for write in bundle["writes"]:
            if self._classify(write) != "new":
                raise TransactionError(f"applied-state verification failed: {write['path']}")
        state_value["phase"] = "applied"
        state_value["recovery_direction"] = "applied"
        self._write_state(op_dir, state_value)

    def _perform_rollback(self, op_dir: Path, bundle: dict, state_value: dict) -> None:
        snapshots = self._snapshot_applied_for_rollback(op_dir, bundle)
        self._hit("after-rollback-snapshot")
        created_archive = op_dir / "rollback-created"
        restore_root = op_dir / "rollback-original"
        self._mkdir_durable(created_archive)
        self._mkdir_durable(restore_root)
        state_value["phase"] = "rolling-back"
        state_value["recovery_direction"] = "applied"
        self._write_state(op_dir, state_value)
        try:
            for write in reversed(bundle["writes"]):
                relative = PurePosixPath(write["path"])
                target = self._target(relative)
                if self._classify(write) != "new":
                    raise TransactionError(f"rollback target changed: {relative}", 3)
                if write["mode"] == "create":
                    self._ensure_tree(created_archive, relative.parent)
                    archive = created_archive.joinpath(*relative.parts)
                    os.replace(target, archive)
                    self._event(f"replace:{target}->{archive}")
                    self._fsync_file(archive)
                    self._fsync_dir(target.parent)
                    self._fsync_dir(archive.parent)
                else:
                    original = op_dir.joinpath("originals", *relative.parts)
                    self._replace_from_snapshot(original, target, relative, self._expected_original(write), restore_root)
                self._hit(f"after-rollback-live:{relative}")
            for write in bundle["writes"]:
                if self._fingerprint(self._target(PurePosixPath(write["path"]))) != self._expected_original(write):
                    raise TransactionError(f"rollback verification failed: {write['path']}")
            state_value["phase"] = "rolled-back"
            state_value["recovery_direction"] = "original"
            self._write_state(op_dir, state_value)
        except Exception as exc:
            state_value["phase"] = "recovery-required"
            state_value["recovery_direction"] = "applied"
            with contextlib.suppress(Exception):
                self._write_state(op_dir, state_value)
            try:
                self._restore_applied(op_dir, bundle, state_value)
            except Exception as repair_exc:
                raise TransactionError(f"rollback interrupted; applied-state recovery required: {exc}; {repair_exc}", 6) from exc
            raise TransactionError(f"rollback failed; applied state restored: {exc}", 6) from exc

    def rollback(self, operation_id: str, approval_sha256: str) -> dict:
        preview = self.rollback_plan(operation_id)
        if approval_sha256 != preview["approval_sha256"]:
            raise TransactionError("approval hash does not match rollback plan", 4)
        with self._lock():
            preview = self.rollback_plan(operation_id)
            if approval_sha256 != preview["approval_sha256"]:
                raise TransactionError("rollback plan changed after approval", 4)
            op_dir, bundle, state_value = self._load_journal(operation_id)
            self._perform_rollback(op_dir, bundle, state_value)
            return {
                "operation_id": operation_id,
                "state": "rolled-back",
                "journal": str(op_dir),
                "changed_paths": [str(self._target(PurePosixPath(w["path"]))) for w in bundle["writes"]],
            }

    def recover_plan(self, operation_id: str) -> dict:
        op_dir, bundle, state_value = self._load_journal(operation_id)
        phase = state_value["phase"]
        direction = state_value.get("recovery_direction", "original")
        if phase == "applied":
            raise TransactionError("applied transaction needs rollback, not recover")
        if phase == "rolled-back":
            return {"action": "recover", "operation_id": operation_id, "state": "rolled-back", "needed": False}
        if phase == "rolling-back":
            direction = "applied"
        elif phase in {"prepared", "applying"}:
            direction = "original"
        elif phase != "recovery-required":
            raise TransactionError(f"unsupported recovery state: {phase}")
        if direction not in {"original", "applied"}:
            raise TransactionError(f"invalid recovery direction: {direction}")
        for write in bundle["writes"]:
            classification = self._classify(write)
            if classification not in {"original", "new"}:
                raise TransactionError(f"recover refuses unexpected target: {write['path']}", 3)
            if direction == "applied":
                snapshot = op_dir.joinpath("rollback-current", *PurePosixPath(write["path"]).parts)
                if self._fingerprint(snapshot) != self._expected_new(write):
                    raise TransactionError(f"applied recovery snapshot missing or changed: {write['path']}")
            elif write["mode"] == "replace":
                original = op_dir.joinpath("originals", *PurePosixPath(write["path"]).parts)
                if self._fingerprint(original) != self._expected_original(write):
                    raise TransactionError(f"original recovery snapshot missing or changed: {write['path']}")
        return self._action_approval("recover", operation_id, direction, bundle, state_value)

    def recover(self, operation_id: str, approval_sha256: str) -> dict:
        preview = self.recover_plan(operation_id)
        if not preview.get("needed", True):
            return preview
        if approval_sha256 != preview["approval_sha256"]:
            raise TransactionError("approval hash does not match recovery plan", 4)
        with self._lock():
            preview = self.recover_plan(operation_id)
            if approval_sha256 != preview["approval_sha256"]:
                raise TransactionError("recovery plan changed after approval", 4)
            op_dir, bundle, state_value = self._load_journal(operation_id)
            if preview["direction"] == "original":
                self._restore_original(op_dir, bundle, state_value)
                final = "rolled-back"
            else:
                self._restore_applied(op_dir, bundle, state_value)
                final = "applied"
            return {
                "operation_id": operation_id,
                "state": final,
                "journal": str(op_dir),
                "changed_paths": [str(self._target(PurePosixPath(w["path"]))) for w in bundle["writes"]],
            }

    def status(self, operation_id: str) -> dict:
        op_dir, _, state_value = self._load_journal(operation_id)
        return {"operation_id": operation_id, "state": state_value["phase"], "journal": str(op_dir)}

    def list_operations(self) -> dict:
        if _lstat(self.runtime) is None:
            return {"operations": []}
        self._ensure_runtime()
        operations = []
        for path in sorted(self.runtime.iterdir()):
            if path.name == "lock":
                continue
            info = _lstat(path)
            if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                operations.append({"operation_id": path.name, "state": "unsafe-entry"})
                continue
            try:
                state_value = self._state(path)
                operations.append({"operation_id": path.name, "state": state_value["phase"]})
            except TransactionError as exc:
                operations.append({"operation_id": path.name, "state": "invalid", "error": str(exc)})
        return {"operations": operations}


def _default_engine() -> TransactionEngine:
    return TransactionEngine(Path(__file__).resolve().parent.parent)


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="create an exclusive canonical bundle outside the vault")
    prepare.add_argument("spec", type=Path)
    prepare.add_argument("--bundle", type=Path, required=True)

    inspect = sub.add_parser("inspect", help="preview an apply and print its approval hash")
    inspect.add_argument("bundle", type=Path)

    apply_cmd = sub.add_parser("apply", help="apply an inspected bundle")
    apply_cmd.add_argument("bundle", type=Path)
    apply_cmd.add_argument("--approved-plan-sha256", required=True)

    rollback = sub.add_parser("rollback", help="preview or apply rollback of an applied operation")
    rollback.add_argument("operation_id")
    rollback.add_argument("--apply", action="store_true")
    rollback.add_argument("--approved-plan-sha256")

    recover = sub.add_parser("recover", help="preview or apply recovery of an interrupted operation")
    recover.add_argument("operation_id")
    recover.add_argument("--apply", action="store_true")
    recover.add_argument("--approved-plan-sha256")

    status_cmd = sub.add_parser("status", help="show one operation state")
    status_cmd.add_argument("operation_id")
    sub.add_parser("list", help="list journaled operations")

    args = parser.parse_args(argv)
    engine = _default_engine()
    try:
        if args.command == "prepare":
            result = engine.prepare(args.spec, args.bundle)
        elif args.command == "inspect":
            result = engine.inspect(args.bundle)
        elif args.command == "apply":
            result = engine.apply(args.bundle, args.approved_plan_sha256)
        elif args.command == "rollback":
            if args.apply:
                if not args.approved_plan_sha256:
                    raise TransactionError("rollback --apply requires --approved-plan-sha256", 4)
                result = engine.rollback(args.operation_id, args.approved_plan_sha256)
            else:
                if args.approved_plan_sha256:
                    raise TransactionError("approval hash is only accepted with rollback --apply")
                result = engine.rollback_plan(args.operation_id)
        elif args.command == "recover":
            if args.apply:
                if not args.approved_plan_sha256:
                    raise TransactionError("recover --apply requires --approved-plan-sha256", 4)
                result = engine.recover(args.operation_id, args.approved_plan_sha256)
            else:
                if args.approved_plan_sha256:
                    raise TransactionError("approval hash is only accepted with recover --apply")
                result = engine.recover_plan(args.operation_id)
        elif args.command == "status":
            result = engine.status(args.operation_id)
        else:
            result = engine.list_operations()
        _print(result)
        return 0
    except TransactionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
