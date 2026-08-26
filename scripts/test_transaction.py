#!/usr/bin/env python3
"""Isolated tests for scripts/transaction.py."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from transaction import (
    BUNDLE_SCHEMA,
    SPEC_SCHEMA,
    TransactionEngine,
    TransactionError,
)


class InjectedCrash(BaseException):
    """Simulate process death; transaction handlers intentionally do not catch it."""


class TransactionHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="litwiki-transaction-test-")
        self.base = Path(self.temp.name)
        self.vault = self.base / "vault"
        self.scratch = self.base / "scratch"
        self.vault.mkdir()
        self.scratch.mkdir()
        for folder in ("lit", "claims", "concepts", "mocs", "qa", "meta", "scripts"):
            (self.vault / folder).mkdir()
        (self.vault / "_catalog.md").write_bytes(b"old catalog\n")
        self.engine = TransactionEngine(self.vault)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_bundle(
        self,
        operation_id: str,
        writes: list[tuple[str, bytes]],
        *,
        engine: TransactionEngine | None = None,
        bundle_name: str | None = None,
    ) -> tuple[Path, dict[str, Path]]:
        engine = engine or self.engine
        draft_dir = self.scratch / f"drafts-{operation_id}-{len(list(self.scratch.iterdir()))}"
        draft_dir.mkdir()
        paths: dict[str, Path] = {}
        spec_writes = []
        for index, (target, content) in enumerate(writes):
            draft = draft_dir / f"draft-{index}.md"
            draft.write_bytes(content)
            paths[target] = draft
            spec_writes.append({"path": target, "content_file": str(draft)})
        spec = self.scratch / f"{operation_id}-{len(list(self.scratch.iterdir()))}.spec.json"
        spec.write_text(
            json.dumps({"schema": SPEC_SCHEMA, "operation_id": operation_id, "writes": spec_writes}),
            encoding="utf-8",
        )
        bundle = self.scratch / (bundle_name or f"{operation_id}-{len(list(self.scratch.iterdir()))}.bundle.json")
        engine.prepare(spec, bundle)
        return bundle, paths

    def apply_bundle(self, bundle: Path, *, engine: TransactionEngine | None = None) -> dict:
        engine = engine or self.engine
        preview = engine.inspect(bundle)
        return engine.apply(bundle, preview["approval_sha256"])


class ApplyRollbackTests(TransactionHarness):
    def test_mixed_apply_and_exact_rollback(self) -> None:
        bundle, _ = self.make_bundle(
            "mixed-apply",
            [("_catalog.md", b"new catalog\n"), ("mocs/moc-new.md", b"# new\n")],
        )
        result = self.apply_bundle(bundle)
        self.assertEqual(result["state"], "applied")
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"new catalog\n")
        self.assertEqual((self.vault / "mocs/moc-new.md").read_bytes(), b"# new\n")

        preview = self.engine.rollback_plan("mixed-apply")
        rolled = self.engine.rollback("mixed-apply", preview["approval_sha256"])
        self.assertEqual(rolled["state"], "rolled-back")
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")
        self.assertFalse((self.vault / "mocs/moc-new.md").exists())
        self.assertEqual(
            (self.vault / ".transactions/mixed-apply/rollback-current/mocs/moc-new.md").read_bytes(),
            b"# new\n",
        )
        self.assertEqual(self.engine.status("mixed-apply")["state"], "rolled-back")

    def test_wrong_approval_does_not_write(self) -> None:
        bundle, _ = self.make_bundle("bad-approval", [("_catalog.md", b"new\n")])
        with self.assertRaises(TransactionError) as caught:
            self.engine.apply(bundle, "0" * 64)
        self.assertEqual(caught.exception.exit_code, 4)
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")

    def test_changed_draft_and_stale_target_refuse_before_write(self) -> None:
        draft_bundle, drafts = self.make_bundle("draft-drift", [("_catalog.md", b"new\n")])
        drafts["_catalog.md"].write_bytes(b"changed after prepare\n")
        with self.assertRaises(TransactionError):
            self.engine.inspect(draft_bundle)
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")

        stale_bundle, _ = self.make_bundle("target-drift", [("_catalog.md", b"newer\n")])
        (self.vault / "_catalog.md").write_bytes(b"external edit\n")
        with self.assertRaises(TransactionError):
            self.engine.inspect(stale_bundle)
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"external edit\n")

    def test_mid_apply_failure_restores_original_state(self) -> None:
        def failpoint(name: str) -> None:
            if name == "after-live:_catalog.md":
                raise RuntimeError("injected apply failure")

        engine = TransactionEngine(self.vault, failpoint=failpoint)
        bundle, _ = self.make_bundle(
            "mid-apply-failure",
            [("_catalog.md", b"new catalog\n"), ("mocs/moc-new.md", b"# new\n")],
            engine=engine,
        )
        preview = engine.inspect(bundle)
        with self.assertRaises(TransactionError) as caught:
            engine.apply(bundle, preview["approval_sha256"])
        self.assertEqual(caught.exception.exit_code, 6)
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")
        self.assertFalse((self.vault / "mocs/moc-new.md").exists())
        self.assertEqual(engine.status("mid-apply-failure")["state"], "rolled-back")


class RecoveryTests(TransactionHarness):
    def test_crash_after_every_apply_target_recovers_original(self) -> None:
        for index, crash_target in enumerate(("_catalog.md", "mocs/moc-new.md")):
            operation_id = f"apply-crash-{index}"

            def failpoint(name: str, wanted: str = crash_target) -> None:
                if name == f"after-live:{wanted}":
                    raise InjectedCrash(name)

            engine = TransactionEngine(self.vault, failpoint=failpoint)
            bundle, _ = self.make_bundle(
                operation_id,
                [("_catalog.md", b"new catalog\n"), ("mocs/moc-new.md", b"# new\n")],
                engine=engine,
            )
            preview = engine.inspect(bundle)
            with self.assertRaises(InjectedCrash):
                engine.apply(bundle, preview["approval_sha256"])

            fresh = TransactionEngine(self.vault)
            recovery = fresh.recover_plan(operation_id)
            self.assertEqual(recovery["direction"], "original")
            result = fresh.recover(operation_id, recovery["approval_sha256"])
            self.assertEqual(result["state"], "rolled-back")
            self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")
            self.assertFalse((self.vault / "mocs/moc-new.md").exists())

    def test_crash_after_every_rollback_target_recovers_applied_then_retries(self) -> None:
        for index, crash_target in enumerate(("mocs/moc-new.md", "_catalog.md")):
            operation_id = f"rollback-crash-{index}"
            bundle, _ = self.make_bundle(
                operation_id,
                [("_catalog.md", b"new catalog\n"), ("mocs/moc-new.md", b"# new\n")],
            )
            self.apply_bundle(bundle)

            def failpoint(name: str, wanted: str = crash_target) -> None:
                if name == f"after-rollback-live:{wanted}":
                    raise InjectedCrash(name)

            crashing = TransactionEngine(self.vault, failpoint=failpoint)
            rollback = crashing.rollback_plan(operation_id)
            with self.assertRaises(InjectedCrash):
                crashing.rollback(operation_id, rollback["approval_sha256"])

            fresh = TransactionEngine(self.vault)
            recovery = fresh.recover_plan(operation_id)
            self.assertEqual(recovery["direction"], "applied")
            recovered = fresh.recover(operation_id, recovery["approval_sha256"])
            self.assertEqual(recovered["state"], "applied")
            self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"new catalog\n")
            self.assertEqual((self.vault / "mocs/moc-new.md").read_bytes(), b"# new\n")

            retry = fresh.rollback_plan(operation_id)
            result = fresh.rollback(operation_id, retry["approval_sha256"])
            self.assertEqual(result["state"], "rolled-back")
            self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")
            self.assertFalse((self.vault / "mocs/moc-new.md").exists())

    def test_crash_between_rollback_snapshot_and_state_reuses_snapshot(self) -> None:
        operation_id = "rollback-snapshot-crash"
        bundle, _ = self.make_bundle(
            operation_id,
            [("_catalog.md", b"new catalog\n"), ("mocs/moc-new.md", b"# new\n")],
        )
        self.apply_bundle(bundle)

        def failpoint(name: str) -> None:
            if name == "after-rollback-snapshot":
                raise InjectedCrash(name)

        crashing = TransactionEngine(self.vault, failpoint=failpoint)
        preview = crashing.rollback_plan(operation_id)
        with self.assertRaises(InjectedCrash):
            crashing.rollback(operation_id, preview["approval_sha256"])

        fresh = TransactionEngine(self.vault)
        self.assertEqual(fresh.status(operation_id)["state"], "applied")
        retry = fresh.rollback_plan(operation_id)
        result = fresh.rollback(operation_id, retry["approval_sha256"])
        self.assertEqual(result["state"], "rolled-back")
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"old catalog\n")
        self.assertFalse((self.vault / "mocs/moc-new.md").exists())

    def test_recovery_refuses_unexpected_external_edit(self) -> None:
        bundle, _ = self.make_bundle("recover-drift", [("_catalog.md", b"new\n")])
        self.apply_bundle(bundle)
        op_dir, _, state = self.engine._load_journal("recover-drift")
        state["phase"] = "applying"
        state["recovery_direction"] = "original"
        self.engine._write_state(op_dir, state)
        (self.vault / "_catalog.md").write_bytes(b"third-party bytes\n")
        with self.assertRaises(TransactionError) as caught:
            self.engine.recover_plan("recover-drift")
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"third-party bytes\n")


class ConfinementTests(TransactionHarness):
    def write_spec(self, name: str, operation_id: str, writes: list[dict]) -> Path:
        spec = self.scratch / name
        spec.write_text(
            json.dumps({"schema": SPEC_SCHEMA, "operation_id": operation_id, "writes": writes}),
            encoding="utf-8",
        )
        return spec

    def test_target_path_rejections(self) -> None:
        draft = self.scratch / "draft.md"
        draft.write_text("x", encoding="utf-8")
        bad_targets = ["../escape.md", "/absolute.md", ".transactions/x", ".cache/x", "scripts/transaction.py"]
        for index, target in enumerate(bad_targets):
            with self.subTest(target=target):
                spec = self.write_spec(
                    f"bad-target-{index}.json",
                    f"bad-target-{index}",
                    [{"path": target, "content_file": str(draft)}],
                )
                with self.assertRaises(TransactionError):
                    self.engine.prepare(spec, self.scratch / f"bad-target-{index}.bundle")

        duplicate = self.write_spec(
            "duplicate.json",
            "duplicate",
            [
                {"path": "_catalog.md", "content_file": str(draft)},
                {"path": "_catalog.md", "content_file": str(self.scratch / "other.md")},
            ],
        )
        (self.scratch / "other.md").write_text("y", encoding="utf-8")
        with self.assertRaises(TransactionError):
            self.engine.prepare(duplicate, self.scratch / "duplicate.bundle")

    def test_symlink_target_and_invalid_operation_id_reject(self) -> None:
        outside = self.scratch / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        os.symlink(outside, self.vault / "lit/link.md")
        draft = self.scratch / "draft.md"
        draft.write_text("new", encoding="utf-8")
        symlink_spec = self.write_spec(
            "symlink.json",
            "symlink-target",
            [{"path": "lit/link.md", "content_file": str(draft)}],
        )
        with self.assertRaises(TransactionError):
            self.engine.prepare(symlink_spec, self.scratch / "symlink.bundle")
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside")

        invalid = self.write_spec(
            "invalid-id.json",
            "../journal-escape",
            [{"path": "_catalog.md", "content_file": str(draft)}],
        )
        with self.assertRaises(TransactionError):
            self.engine.prepare(invalid, self.scratch / "invalid-id.bundle")

    def test_bundle_location_identity_and_existing_file_reject(self) -> None:
        draft = self.scratch / "draft.md"
        draft.write_text("new", encoding="utf-8")
        spec = self.write_spec(
            "safe.spec.json",
            "bundle-safety",
            [{"path": "_catalog.md", "content_file": str(draft)}],
        )
        with self.assertRaises(TransactionError):
            self.engine.prepare(spec, self.vault / "bundle.json")
        self.assertFalse((self.vault / "bundle.json").exists())

        existing = self.scratch / "existing.bundle"
        existing.write_bytes(b"preserve me")
        with self.assertRaises(TransactionError):
            self.engine.prepare(spec, existing)
        self.assertEqual(existing.read_bytes(), b"preserve me")

        with self.assertRaises(TransactionError):
            self.engine.prepare(spec, spec)
        self.assertIn("bundle-safety", spec.read_text(encoding="utf-8"))
        with self.assertRaises(TransactionError):
            self.engine.prepare(spec, draft)
        self.assertEqual(draft.read_text(encoding="utf-8"), "new")

        link = self.scratch / "bundle-link"
        os.symlink(existing, link)
        with self.assertRaises(TransactionError):
            self.engine.prepare(spec, link)
        self.assertEqual(existing.read_bytes(), b"preserve me")

    def test_content_symlink_and_duplicate_file_identity_reject(self) -> None:
        real = self.scratch / "real-draft.md"
        real.write_text("new", encoding="utf-8")
        symlink = self.scratch / "symlink-draft.md"
        os.symlink(real, symlink)
        symlink_spec = self.write_spec(
            "content-symlink.json",
            "content-symlink",
            [{"path": "_catalog.md", "content_file": str(symlink)}],
        )
        with self.assertRaises(TransactionError):
            self.engine.prepare(symlink_spec, self.scratch / "content-symlink.bundle")

        hardlink = self.scratch / "hardlink-draft.md"
        os.link(real, hardlink)
        duplicate_identity = self.write_spec(
            "duplicate-identity.json",
            "duplicate-identity",
            [
                {"path": "_catalog.md", "content_file": str(real)},
                {"path": "mocs/second.md", "content_file": str(hardlink)},
            ],
        )
        with self.assertRaises(TransactionError):
            self.engine.prepare(duplicate_identity, self.scratch / "duplicate-identity.bundle")

    def test_reused_or_symlink_journal_refuses(self) -> None:
        first, _ = self.make_bundle("reuse-id", [("_catalog.md", b"first\n")])
        self.apply_bundle(first)
        second, _ = self.make_bundle("reuse-id", [("_catalog.md", b"second\n")], bundle_name="reuse-second.bundle")
        preview = self.engine.inspect(second)
        with self.assertRaises(TransactionError):
            self.engine.apply(second, preview["approval_sha256"])
        self.assertEqual((self.vault / "_catalog.md").read_bytes(), b"first\n")

        bundle, _ = self.make_bundle("journal-link", [("mocs/link-test.md", b"new\n")])
        outside = self.scratch / "journal-outside"
        outside.mkdir()
        os.symlink(outside, self.vault / ".transactions/journal-link")
        preview = self.engine.inspect(bundle)
        with self.assertRaises(TransactionError):
            self.engine.apply(bundle, preview["approval_sha256"])
        self.assertFalse((self.vault / "mocs/link-test.md").exists())


class DurabilityOrderTests(TransactionHarness):
    def assert_file_mutation_durable(self, events: list[str], boundary: int, target: Path) -> None:
        mutation_index = None
        source = destination = None
        for index in range(boundary - 1, -1, -1):
            event = events[index]
            if not (event.startswith("replace:") or event.startswith("link:")):
                continue
            left, right = event.split(":", 1)[1].split("->", 1)
            if left == str(target) or right == str(target):
                mutation_index = index
                source, destination = Path(left), Path(right)
                break
        self.assertIsNotNone(mutation_index, f"no file mutation found for {target}")
        segment = events[mutation_index + 1:boundary]
        self.assertIn(f"file-fsync:{destination}", segment)
        self.assertIn(f"dir-fsync:{source.parent}", segment)
        self.assertIn(f"dir-fsync:{destination.parent}", segment)

    def test_apply_and_rollback_mutations_have_exact_fsyncs(self) -> None:
        events: list[str] = []
        engine = TransactionEngine(self.vault, event_sink=events.append)
        bundle, _ = self.make_bundle(
            "durability-order",
            [("_catalog.md", b"new catalog\n"), ("mocs/moc-new.md", b"# new\n")],
            engine=engine,
        )
        self.apply_bundle(bundle, engine=engine)

        first_live = next(i for i, event in enumerate(events) if event.startswith("live-installed:"))
        verified = [i for i, event in enumerate(events) if event.startswith("snapshot-verified:")]
        self.assertTrue(verified)
        self.assertLess(max(verified), first_live)

        for index, event in enumerate(events):
            if event.startswith("live-installed:"):
                relative = event.split(":", 1)[1]
                self.assert_file_mutation_durable(events, index, engine.vault / relative)

        applied_index = events.index("state:applied")
        last_live = max(i for i, event in enumerate(events) if event.startswith("live-installed:"))
        self.assertLess(last_live, applied_index)
        self.assertTrue(any("result.json" in event for event in events[last_live:applied_index]))

        events.clear()
        rollback = engine.rollback_plan("durability-order")
        engine.rollback("durability-order", rollback["approval_sha256"])
        boundaries = [
            (index, event.split("after-rollback-live:", 1)[1])
            for index, event in enumerate(events)
            if event.startswith("failpoint:after-rollback-live:")
        ]
        self.assertEqual({relative for _, relative in boundaries}, {"_catalog.md", "mocs/moc-new.md"})
        for index, relative in boundaries:
            self.assert_file_mutation_durable(events, index, engine.vault / relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
