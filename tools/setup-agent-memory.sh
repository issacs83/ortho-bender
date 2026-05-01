#!/usr/bin/env bash
# Setup Claude Code agent memory symlink to repo-tracked AGENT_MEMORY directory.
# Run once per machine after cloning the repo.
#
# Why: Claude Code reads/writes memory at ~/.claude/projects/<encoded-path>/memory/
#      To keep memory in sync across machines we store it in the repo at
#      .claude/AGENT_MEMORY/ and symlink the local memory dir to it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_MEM="${REPO_ROOT}/.claude/AGENT_MEMORY"

if [[ ! -d "${REPO_MEM}" ]]; then
    echo "ERROR: ${REPO_MEM} not found. Run from a clone that includes AGENT_MEMORY." >&2
    exit 1
fi

# Claude Code encodes the project absolute path into ~/.claude/projects/<encoded>/
# Encoding rule: replace '/' with '-' and prefix with '-'
ENCODED="$(echo "${REPO_ROOT}" | sed 's|/|-|g')"
LOCAL_MEM="${HOME}/.claude/projects/${ENCODED}/memory"
LOCAL_PARENT="$(dirname "${LOCAL_MEM}")"

mkdir -p "${LOCAL_PARENT}"

if [[ -L "${LOCAL_MEM}" ]]; then
    CURRENT_TARGET="$(readlink -f "${LOCAL_MEM}")"
    if [[ "${CURRENT_TARGET}" == "$(readlink -f "${REPO_MEM}")" ]]; then
        echo "OK: ${LOCAL_MEM} already symlinked to ${REPO_MEM}"
        exit 0
    fi
    echo "INFO: existing symlink points to ${CURRENT_TARGET}; replacing"
    rm "${LOCAL_MEM}"
elif [[ -e "${LOCAL_MEM}" ]]; then
    BACKUP="${LOCAL_MEM}.backup-$(date +%Y%m%d-%H%M%S)"
    echo "INFO: backing up existing memory to ${BACKUP}"
    mv "${LOCAL_MEM}" "${BACKUP}"
fi

ln -s "${REPO_MEM}" "${LOCAL_MEM}"
echo "OK: ${LOCAL_MEM} -> ${REPO_MEM}"
echo ""
echo "Verify:"
ls -la "${LOCAL_MEM}/"
