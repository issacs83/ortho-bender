# Agent Memory (Claude Code persistent context)

이 디렉터리는 Claude Code 에이전트의 영구 메모리를 git으로 동기화하기 위한 위치입니다.

## 구조
- `MEMORY.md` — 인덱스 (각 메모리 파일에 대한 한 줄 포인터)
- `*.md` — 개별 메모리 파일 (frontmatter + 본문)

## 새 머신에서 셋업

Claude Code가 메모리를 읽는 기본 경로는 `~/.claude/projects/<encoded-project-path>/memory/`.
이 디렉터리를 레포 안 위치로 심볼릭 링크해야 동기화됩니다.

```bash
# 레포 루트에서 실행
./tools/setup-agent-memory.sh
```

## 수동 셋업 (스크립트 안 쓸 때)

```bash
REPO_MEM="$(pwd)/.claude/AGENT_MEMORY"
LOCAL_MEM="$HOME/.claude/projects/-home-issacs-work-quarkers-ortho-bender/memory"

# 기존 로컬 메모리 백업
[ -e "$LOCAL_MEM" ] && mv "$LOCAL_MEM" "${LOCAL_MEM}.backup-$(date +%Y%m%d-%H%M%S)"

# 심볼릭 링크
mkdir -p "$(dirname "$LOCAL_MEM")"
ln -s "$REPO_MEM" "$LOCAL_MEM"
```

## 주의
- `~/.claude/projects/...` 의 인코딩된 경로는 **레포가 클론된 절대 경로**에 따라 달라집니다
- 다른 경로에 클론한 경우, Claude Code가 새 인코딩으로 메모리 폴더를 만들 수 있음 — 셋업 스크립트가 이걸 자동 처리합니다
