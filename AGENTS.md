## Delivery doctrine: worktree → branch → PR → preview

Every implementation task must be delivered through a pull request
with a reviewable preview environment when the change is deployable.

### Workspace and branch
- Inspect the current repository, branch, worktree and working changes
  before editing.
- Use one dedicated Git worktree and feature branch per independent task.
- If Orca already created the correct worktree and branch, reuse them.
  Do not create a nested or duplicate worktree.
- Start new independent tasks from the latest origin/main unless the
  task explicitly specifies another base.
- Never implement or commit changes on main, master or a release branch.
- Preserve unrelated changes and other agents' work.

### Publishing
- For an assigned implementation task, pushing its feature branch and
  opening or updating its PR are authorized parts of delivery, unless
  the user explicitly requests local-only work.
- Never push directly to main, master or a release branch.
- Never force-push, bypass branch protection or merge a PR.
- Run the repository's required checks before publishing.
- Review staged changes for unintended files and secrets.
- Push only the task's feature branch.
- Open a draft PR once there is a meaningful, deployable change.
- If that branch already has an open PR, update it rather than creating
  another PR.
- Keep incomplete work in draft and report failing or blocked checks.

### Preview and review
- Let the configured Coolify PR integration deploy the preview.
- Use only preview credentials and isolated preview data.
- Check deployment status and verify the preview corresponds to the
  latest pushed commit.
- Obtain the actual preview URL from Coolify or its PR comment.
  Never invent a URL or claim an unverified deployment is healthy.
- Keep the PR description updated with the purpose, changes, checks,
  preview URL and any limitations.
- If preview deployment fails, fix task-related failures where possible;
  otherwise report the blocker clearly.
- Finish by reporting the PR URL, preview URL, tested commit and checks.
- Leave merging and closing the PR to a human.
