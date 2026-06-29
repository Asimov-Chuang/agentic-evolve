#!/usr/bin/env bash
# Add OpenCode to PATH for the current shell session.
# Usage: source setup-path.sh

export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"

if command -v opencode >/dev/null 2>&1; then
  echo "OpenCode $(opencode --version) is available."
else
  echo "OpenCode not found. Install with:"
  echo "  curl -fsSL https://opencode.ai/install | bash"
  return 1 2>/dev/null || exit 1
fi
