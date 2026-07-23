---
name: GitHub source-control picker
description: Replit account-level GitHub picker can become stale independently of the repository's local git remote.
---

When Replit's “Connect to GitHub” picker shows an old repository while the local `origin` remote is correct, refresh the Git Providers connection in Replit account settings by disconnecting and reconnecting GitHub.

**Why:** The picker is powered by Replit's account-level GitHub OAuth connection, not by the repository's local `origin` configuration or a project secret token.

**How to apply:** Verify `git remote -v` and the remote branch first. If they point to the intended repository, do not rewrite or force-push; have the user refresh Git Providers, then reopen the Git pane.