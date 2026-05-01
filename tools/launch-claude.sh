#!/usr/bin/env bash
# Launch (or attach to) a persistent Claude Code session inside tmux.
# Usage: ./tools/launch-claude.sh
#
# - SSH 끊겨도 세션 유지
# - 재접속 시 attach만 하면 같은 대화로 복귀
# - 텔레그램 플러그인 채널 자동 연동

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_NAME="ortho-bender"

# AGENT_MEMORY 셋업이 안 되어 있으면 먼저 실행
if [[ ! -L "${HOME}/.claude/projects/$(echo "${REPO_ROOT}" | sed 's|/|-|g')/memory" ]]; then
    echo "INFO: Setting up agent memory symlink first..."
    "${REPO_ROOT}/tools/setup-agent-memory.sh"
fi

# tmux 미설치 시 안내
if ! command -v tmux >/dev/null 2>&1; then
    echo "ERROR: tmux not installed. Install it: sudo apt install tmux" >&2
    exit 1
fi

# 기존 세션이 있으면 attach
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "INFO: Attaching to existing session '${SESSION_NAME}'"
    exec tmux attach -t "${SESSION_NAME}"
fi

# 새 세션 시작
echo "INFO: Creating new tmux session '${SESSION_NAME}'"
cd "${REPO_ROOT}"

CLAUDE_CMD="claude --resume --dangerously-skip-permissions --channels plugin:telegram@claude-plugins-official"

tmux new-session -d -s "${SESSION_NAME}" -c "${REPO_ROOT}" "${CLAUDE_CMD}"
echo "OK: Session started. Attach with:"
echo "  tmux attach -t ${SESSION_NAME}"
echo ""
echo "Detach later with: Ctrl+B then D"
echo "List sessions:     tmux ls"
echo "Kill session:      tmux kill-session -t ${SESSION_NAME}"
echo ""
echo "Attaching now..."
exec tmux attach -t "${SESSION_NAME}"
