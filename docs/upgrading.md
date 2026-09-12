# Creating and upgrading a private vault

Maintain reusable rules in the workflow repository and ingest real sources only
in a separate private vault. The workflow checkout is a distribution package.

1. For a new vault, use GitHub **Use this template** and choose **Private**.
   Alternatively clone locally and set its remote to your own private repository
   before committing personal material. Template copies do not receive updates.
2. Record the workflow version in your private project notes. Before upgrading,
   commit your private vault and inspect the upstream diff from that version.
3. Review changes to `scripts/`, `meta/AI-GUIDE.md`, `meta/SCHEMA.md`,
   `meta/WORKFLOW.md`, `meta/QUALITY.md`, task prompts and templates. Apply only
   intended common changes. Keep your own `INSTRUCTIONS.md`, `VOCAB.md`, paths,
   source/integration records, bibliography, catalog, notes and log.
4. Run `search.py --self-test`, `health.py --self-test`,
   `eval_human.py --self-test`, and the validator; inspect the health report.
   A new feature may show legacy records as unrecorded rather than inventing
   completion history. Commit the upgrade with its upstream version.

The template's `template` Actions workflow checks the distribution package,
including empty data directories. Disable that workflow in a populated private
copy, or replace it with your own vault validation workflow. Do not weaken the
public package check to accommodate private content.

## Preparing a workflow release

Run `python3 -B scripts/check_template.py`, `python3 -B scripts/demo.py`, and
the existing transaction tests. Review all staged files and the repository
history before changing visibility. The allowlist is an extra distribution
check, not a secret scanner and not proof that history is safe.

Use a version tag and release notes to identify tested common files. Enable
Template in repository settings. Visibility is a separate choice; enabling
Template does not publish a private repository. First release candidate: v0.1.0.

References: [GitHub templates](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository),
[creating from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template).
