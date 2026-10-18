# GitHub development admission

Own applications use feature/fix -> develop -> release -> main. A selective
release can start at a historical feature commit accepted by a real develop PR;
its complete head must remain reachable from develop. This preserves unfinished
work on develop without manufacturing ancestry or merging unapproved features.
External forks use their maintained main/<line> branch through a reviewed PR.

Dinext policy runs pinned trusted code without executing the PR. The trusted
registry, not a proposed gitflow flag, selects the route and validation profile.
Every maintained line requires its applicable validation and policy status.

An interface change needs an executed successful GitHub Actions check named
`Cypress acceptance`; a runtime change to an external fork also needs
`Compatibility acceptance`. Evidence must belong to the exact current PR head
or test-merge SHA; skipped checks and other revisions do not qualify. Run these
checks in a read-only `Dinext acceptance` workflow or add applicable jobs to
`Dinext validation`. Policy refreshes when either workflow completes. Include
the repeatable test command, fixtures, JUnit output and artifact in that job;
one tested browser scenario per specified user scenario. CI/docs-only changes
do not require browser checks. Validation jobs receive no production secrets.

Before a future release, use the pinned shared `.github/ci/prepare_release.py`
with repository, stable branch, exact SHA, proposed tag and output path. It is
read-only: it validates version/CI and writes a preparation record. Creating a
tag or Release requires the owner's separate publishing decision and reviewed
release notes, compatibility evidence and manifest. Existing tags are immutable.

Deployment, publishing, paid agents, live smoke and external notifications remain
disabled. Imported upstream workflows remain under imported-workflows-disabled.
