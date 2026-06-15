#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# push-to-github.sh
# Creates the GitHub repo and pushes all project files.
#
# Prerequisites:
#   - Git installed  (git --version)
#   - GitHub CLI installed  (brew install gh  OR  https://cli.github.com)
#   - Logged in to GitHub CLI  (gh auth login)
#
# Usage:
#   chmod +x push-to-github.sh
#   ./push-to-github.sh
# ──────────────────────────────────────────────────────────────────────────────

set -e

REPO_NAME="agnes-research-skill"
DESCRIPTION="Deep topic research across Reddit, HN, Polymarket & web — orchestrated by Agnes 2.0 Flash with Thinking mode"

# ── Preflight checks ──────────────────────────────────────────────────────────
echo "🔍 Checking prerequisites..."

if ! command -v git &>/dev/null; then
  echo "❌ git not found. Install: https://git-scm.com"
  exit 1
fi

if ! command -v gh &>/dev/null; then
  echo "❌ GitHub CLI (gh) not found."
  echo "   Install: brew install gh   OR   https://cli.github.com"
  exit 1
fi

if ! gh auth status &>/dev/null; then
  echo "❌ Not logged in to GitHub CLI."
  echo "   Run: gh auth login"
  exit 1
fi

GH_USER=$(gh api user --jq '.login')
echo "✅ Logged in as: $GH_USER"

# ── Init git if needed ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".git" ]; then
  echo "📁 Initializing git repository..."
  git init
  git branch -M main
fi

# ── Create .gitignore ─────────────────────────────────────────────────────────
cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
*.egg-info/
.env
.env.*
*.log
~/Documents/AgnesResearch/
.DS_Store
EOF

# ── Stage all files ───────────────────────────────────────────────────────────
echo "📦 Staging files..."
git add .
git status --short

# ── Initial commit ────────────────────────────────────────────────────────────
if git diff --cached --quiet; then
  echo "ℹ️  Nothing to commit."
else
  git commit -m "feat: Agnes Research Skill v1.0.0

- Agnes 2.0 Flash orchestrator with tool calling + Thinking mode
- Rich terminal UI with live source tracking (tui.py)
- Connectors: Reddit (public JSON), HN (Algolia), Polymarket (Gamma), Web (Brave/DDG)
- Agnes Image 2.1 Flash visual report cover (--image)
- Agnes Video V2.0 animated brief (--video)
- Adapted from mvanhorn/last30days-skill (MIT)"
  echo "✅ Committed."
fi

# ── Create GitHub repo ────────────────────────────────────────────────────────
echo ""
echo "🚀 Creating GitHub repository: $GH_USER/$REPO_NAME..."

if gh repo view "$GH_USER/$REPO_NAME" &>/dev/null; then
  echo "ℹ️  Repo already exists — skipping creation."
else
  gh repo create "$REPO_NAME" \
    --public \
    --description "$DESCRIPTION" \
    --source=. \
    --remote=origin \
    --push
  echo "✅ Repo created and pushed!"
  echo "   👉 https://github.com/$GH_USER/$REPO_NAME"
  exit 0
fi

# ── Push to existing repo ─────────────────────────────────────────────────────
if ! git remote get-url origin &>/dev/null; then
  git remote add origin "https://github.com/$GH_USER/$REPO_NAME.git"
fi

git push -u origin main
echo ""
echo "✅ Done!"
echo "   👉 https://github.com/$GH_USER/$REPO_NAME"
