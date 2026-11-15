---
description: Pull Request creation flow based on git flow
---

# PR Creation Flow

Pull Request creation flow based on git flow.
main branch is for production, develop branch is for development, release branch is for staging.
Summarize and list the work appropriately to create the Pull Request.

## Branch Strategy and Merge Targets

- `feature/*` → `develop`
- `develop` → `release/v*.*.*`
- `release/v*.*.*` → `main`
- `hotfix/*` → `main`

## Merge Methods

| PR | Merge method |
|----|--------------|
| `feature/*` → `develop` | Squash merge OK |
| `release/v*.*.*` → `main` | **"Create a merge commit" ONLY** |
| `hotfix/*` → `main` | **"Create a merge commit" ONLY** |

- **Never squash-merge into `main`.** A squash commit shares no history with `develop`, so the merge-base stays stale and the next release PR conflicts on every previously released file (happened with v0.3.0 / PR #395, repaired in v0.3.1 / PR #401).
- The `git-flow-main` ruleset enforces merge-commit-only on `main`.
- After merging `hotfix/*` into `main`, back-merge `main` into `develop` via PR (also with a merge commit).

## Steps

### 1. Check Commit History

```bash
git log --oneline -10
git log --graph --oneline --all -10
```

### 2. Check Current Branch

```bash
git branch -a
```

### 3. Prepare PR Template

```bash
cp .github/PULL_REQUEST_TEMPLATE.md tmp-pull-request-template.tmp
```

### 4. Edit PR Content

Open `tmp-pull-request-template.tmp` and fill in the sections by summarizing and listing the work done.

### 6. Create Pull Request

#### For feature/* branches

1. **Select Label**

    ```bash
    # Select an appropriate label from the list
    gh label list
    ```

2. **Create PR**

    ```bash
    gh pr create \
    --base develop \
    --head $(git branch --show-current) \
    --title "Set appropriate title" \
    --body-file tmp-pull-request-template.tmp \
    --assignee @me \
    --label "Set appropriate label"
    ```

#### For develop branch

1. **Determine Release Version**
   - Follow semantic versioning (e.g., v1.2.3)
   - MAJOR.MINOR.PATCH format
   - Confirm version with user

2. **Create release branch**

   ```bash
   git fetch origin
   git checkout -b release/v1.2.3 origin/develop

   # Pre-release check: merge-base must be the previous release merge commit.
   # If it is older (stale), histories have diverged (e.g. a squash merge into main).
   git merge-base origin/main origin/develop

   # Only if stale: reconnect histories, keeping develop's content unchanged
   git merge -s ours origin/main -m "🔀 mainの履歴を統合(内容は develop を全面採用)"

   git push -u origin release/v1.2.3
   ```

3. **Create PR**

   ```bash
   gh pr create \
     --base main \
     --head release/v1.2.3 \
     --title "Release v1.2.3" \
     --body-file tmp-pull-request-template.tmp \
     --assignee @me \
     --label release
   ```

#### For release/v*.*.* branches

```bash
gh pr create \
  --base main \
  --head $(git branch --show-current) \
  --title "Set appropriate title" \
  --body-file tmp-pull-request-template.tmp \
  --assignee @me \
  --label release
```

#### For hotfix/* branches

```bash
gh pr create \
  --base main \
  --head $(git branch --show-current) \
  --title "Set appropriate title" \
  --body-file tmp-pull-request-template.tmp \
  --assignee @me \
  --label hotfix
```

### 7. Cleanup

```bash
rm tmp-pull-request-template.tmp
```

## PR Template

```markdown
#### Summary

<!-- Explain the purpose of this PR in 1-3 lines -->

#### Changes

<!-- List changes as bullet points -->
-
-
-

#### Test Plan

<!-- Test methods and verification items -->
- [ ]
- [ ]

#### Comments

<!-- Supplementary notes for reviewers -->
```

## Commit Message Format

```
:<emoji>: <description>

<optional body>
```

| Emoji | Code | Type |
|-------|------|------|
| ✨ | `:sparkles:` | feat |
| 🐛 | `:bug:` | fix |
| ♻️ | `:recycle:` | refactor |
| 📚 | `:books:` | docs |
| ✅ | `:white_check_mark:` | test |
| 🔧 | `:wrench:` | chore |
| ⚡ | `:zap:` | perf |
| 👷 | `:construction_worker:` | ci |
| 🔥 | `:fire:` | remove |
| 🎨 | `:art:` | style |

## Notes

- Always use the Pull Request template
- Add appropriate labels
- **Merge PRs targeting `main` with "Create a merge commit"** — squash breaks history sharing with `develop` and causes conflicts on the next release PR
- Summary should be concise (1-3 lines)
- List changes by logical unit, not by commit
- Include specific verification steps in test plan
- Confirm version with user when creating release branch from develop

## Language

- **All user-facing output, PR titles, and descriptions must be written in Japanese(すべてのユーザーへの出力は日本語にしてください)**
