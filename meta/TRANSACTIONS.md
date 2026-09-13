---
type: meta
name: TRANSACTIONS
description: Design and operator contract for recoverable multi-file litwiki writes.
---

# TRANSACTIONS — recoverable multi-file writes

## Goal

Make a multi-file litwiki mutation all-or-nothing from the operator's point of
view. The first protected workflow is `WORKFLOW.md` §A-5 INTEGRATE, where one
logical change can touch `_catalog.md`, concepts, MOCs, reverse links, qa, and
`meta/log.md`.

This layer protects file state. It does not validate scientific claims and does
not replace `scripts/validate.py`, fulltext verification, bibcheck, or xreview.

## Scope and non-goals

- Add `scripts/transaction.py` with `prepare`, `inspect`, `apply`, `rollback`,
  `recover`, `status`, and `list` commands.
- Support create and replace writes only. Deletion is deliberately unsupported.
- Never clean transaction journals automatically. A rolled-back created file is
  moved into its journal, not deleted.
- Resolve the vault from the script location, never from the caller's cwd.
- Keep runtime state under gitignored `.transactions/`.
- Do not attempt to match claude-obsidian's descriptor-pinned security engine.
  This is a small local tool with explicit limitations documented below.

## Authoring contract

The author prepares complete replacement files in a session scratch directory,
then writes a small JSON spec:

```json
{
  "schema": "litwiki.transaction-spec.v1",
  "operation_id": "integrate-example-20260827",
  "writes": [
    {
      "path": "_catalog.md",
      "content_file": "/tmp/litwiki-example/catalog.md"
    },
    {
      "path": "mocs/moc-example.md",
      "content_file": "/tmp/litwiki-example/moc-example.md"
    }
  ]
}
```

`prepare SPEC --bundle BUNDLE` validates the paths and content files, reads the
current targets, and writes a canonical `litwiki.transaction.v1` bundle. Each
write records:

- vault-relative target path;
- `mode` (`create` when absent, otherwise `replace`);
- expected current SHA-256 (`null` for create);
- content-file path and SHA-256;
- original file mode when replacing.

`SPEC`, `BUNDLE`, and every content file must identify different regular files.
`BUNDLE` must be outside the resolved vault, must not already exist, and must
not be a symlink. `prepare` creates it no-follow and exclusively
(`O_CREAT|O_EXCL|O_NOFOLLOW`); it never truncates or replaces a path supplied by
the operator. Content files must also be outside the vault. The same identity
checks use the opened file descriptors rather than trusting path strings alone.

Target paths must be unique, relative, normalized, and confined to the vault.
Any symlink in a target path is rejected. Content files must be no-follow regular
files. `.git/`, `.transactions/`, `.cache/`, and the transaction script itself
are not valid targets.

`operation_id` is one conservative filename component: ASCII letters, digits,
`.` (not by itself), `_`, and `-`; it may not contain a separator, `..` as a
component, a control character, or begin with `.`. Apply creates
`.transactions/<operation_id>/` with exclusive `mkdir`. An existing file,
directory, or symlink for that ID is a hard refusal; journals are never reused
or overwritten.

## Review and approval

`inspect BUNDLE` is read-only. It revalidates the bundle, target preconditions,
and content hashes, then prints the complete operation and an
`approval_sha256`. The approval hash binds the canonical bundle bytes to the
resolved vault root.

`apply BUNDLE --approved-plan-sha256 HASH` acquires the vault transaction lock,
repeats every check, and refuses if the bundle, draft content, or any target has
changed since inspection. It does not have a force option.

## Apply state machine

Runtime state lives at `.transactions/<operation_id>/`:

```text
bundle.json
state.json
originals/<target path>
staged/<target path>
rollback-current/<target path>
result.json
```

States are:

```text
prepared -> applying -> applied
                    \-> recovery-required -> rolled-back
applied -> rolling-back -> rolled-back
```

Before the first target changes, apply:

1. opens every draft and existing target no-follow as a regular file and copies
   from those pinned descriptors into `staged/` and `originals/`;
2. hashes the bytes actually written to each snapshot and requires equality
   with the bundle's new/original hash;
3. fsyncs every snapshot file, then every parent directory whose entries were
   created, from the leaf directories back through the journal root;
4. records expected original and new hashes in `state.json`, fsyncs that file,
   atomically replaces the prior state, then fsyncs the state parent directory;
5. completes all snapshot checks before modifying the first live target.

It then checks each target precondition again immediately before replacing it
with its staged file using same-filesystem `os.replace`. After each replace or
move, it fsyncs the written file and every source/destination parent directory
whose directory entry changed before persisting the next state step. State and
result transitions use the same order: write and fsync a temporary file,
`os.replace`, fsync its source/destination parent, and only then advance the
recorded state. `applied` is persisted only after every live target has been
opened and hashed to its expected new value. The durability helper and call
order are part of the testable contract, not an implementation detail.

The `fcntl.flock` lock serializes this CLI's writers. Obsidian and unrelated
programs do not honor that lock; hash checks detect their changes before each
write, but the tool cannot eliminate a non-cooperating writer's final
check-to-replace race.

## Failure recovery

An ordinary caught apply failure immediately attempts to restore the original
state. Replaced targets are restored from `originals/`; newly created targets
are moved to `rollback-current/` rather than deleted. If automatic recovery
cannot prove a target is either the expected original or transaction result, it
stops in `recovery-required` without overwriting the unexpected file.

After a process crash, `recover OPERATION_ID` inspects every target against the
recorded original/new hashes and prints a recovery plan plus approval hash.
`recover OPERATION_ID --approved-plan-sha256 HASH --apply` acquires the lock,
rechecks the plan, and chooses its direction solely from the durable state:

- `prepared`, `applying`, or `recovery-required` from apply: restore original;
- `rolling-back`: restore the fully applied state from `rollback-current/` and
  return to `applied`;
- `applied`: refuse and direct the operator to the preview-first `rollback`;
- `rolled-back`: report that no recovery is needed.

Recovery never tries to finish a rollback after `rolling-back`; its one allowed
direction is to undo that interrupted rollback. It refuses targets whose bytes
match neither the recorded original nor applied state. There is no force option.

## Explicit rollback

`rollback OPERATION_ID` is also preview-first. It is allowed only for an
`applied` transaction whose current targets still match `result.json`. The
preview prints the exact affected paths and an approval hash. Applying rollback
requires both `--apply` and that hash.

Before restoring originals, rollback copies the complete applied state to
`rollback-current/`. A created target is moved there so its original path becomes
absent without deletion. If rollback fails partway, those copies restore the
applied state and the operation returns to `applied`; if that repair cannot be
completed, state becomes `recovery-required` with recovery direction recorded
as `applied`. Otherwise the operation ends at `rolled-back`. Rollback never
silently discards edits made after the transaction.

Because rollback replaces existing files or removes created paths from their
current locations, an AI operator must still show the user the full absolute
target list and obtain explicit approval before running the applying form.

## Validation and reporting

The transaction engine guarantees byte-level state transitions, not litwiki
semantics. A transaction that changes canonical vault content must include the
corresponding `meta/log.md` update in the same bundle. After apply, the operator
runs `python3 scripts/validate.py`. If validation fails, the operator previews
and explicitly approves rollback; validation failure does not trigger an
unreviewed rollback automatically.

Successful commands report the operation ID, final state, journal path, and
exact changed paths. Journals remain available for audit and recovery.

## Operator commands

```bash
python3 scripts/transaction.py prepare /tmp/<operation>/spec.json \
  --bundle /tmp/<operation>/bundle.json
python3 scripts/transaction.py inspect /tmp/<operation>/bundle.json
python3 scripts/transaction.py apply /tmp/<operation>/bundle.json \
  --approved-plan-sha256 <inspect-hash>

python3 scripts/transaction.py status <operation_id>
python3 scripts/transaction.py list

# Both commands below preview only:
python3 scripts/transaction.py rollback <operation_id>
python3 scripts/transaction.py recover <operation_id>

# Applying either one requires a fresh preview hash and explicit user approval:
python3 scripts/transaction.py rollback <operation_id> --apply \
  --approved-plan-sha256 <rollback-preview-hash>
python3 scripts/transaction.py recover <operation_id> --apply \
  --approved-plan-sha256 <recover-preview-hash>
```

## Verification plan

Add `scripts/test_transaction.py` using isolated temporary vaults. It must cover:

1. mixed create/replace apply and exact-byte restoration by rollback;
2. approval mismatch, changed draft, and stale target refusal before writes;
3. injected mid-apply failure with automatic restoration;
4. crash after each apply and rollback target, including the fixed recovery
   direction for interrupted rollback, plus refusal on unexpected external edits;
5. traversal, absolute path, duplicate path, protected path, symlink, invalid or
   reused operation ID, bundle-inside-vault, existing bundle, and bundle/spec/
   content identity rejection;
6. fault-injected assertions that snapshot hashes are checked before the first
   live write and every rename is followed by the required file/parent fsyncs
   before the durable state advances.

Run the transaction tests, `python3 scripts/validate.py`, and a syntax check
before declaring the feature complete. Production litwiki content is not used
as a transaction test target.

<!-- XREVIEW-PASS reviewer=codex/gpt-5.6-sol date=2026-08-27 rounds=2 thread=01a03ed5-0dfd-7d80-8616-0c0007dd6a72 -->

## Implementation audit target

The implemented contract is `scripts/transaction.py`; isolated fault,
confinement, durability-order, apply, rollback, and recovery tests are in
`scripts/test_transaction.py`. Reviewers must compare both files against this
document, not review this prose alone. The acceptance commands are:

```bash
python3 -B scripts/test_transaction.py
python3 -B scripts/validate.py
git diff --check
```

<!-- XREVIEW-PASS reviewer=codex/gpt-5.6-sol date=2026-08-27 rounds=2 thread=01a03ee5-3531-7b71-bacb-97b49aa5d7d4 -->
