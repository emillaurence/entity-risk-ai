## Git Commit & Push

Review all staged and unstaged changes in this repo, then:

1. Run `git status` and `git diff` to understand what changed
2. Stage all relevant changes with `git add`
3. Write a commit message following Conventional Commits format:
   - `feat:` new feature
   - `fix:` bug fix
   - `chore:` tooling/config changes
   - `docs:` documentation
   - `refactor:` code restructure without behaviour change
   - Keep subject line under 72 chars
   - Add a short body if the change needs explanation
4. Commit and push to the current branch
5. Report the commit hash and message when done

Do not ask for confirmation — just do it. If there is nothing to commit, say so.
```

---

**Or use it inline as a one-liner prompt in Claude Code:**
```
Review all changes, stage everything, write a conventional commit message based on what changed, commit, and push to current branch. No confirmation needed.