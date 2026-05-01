# External Access — 외부에서 Jun.AI 서버 Claude 세션 이어가기

이 서버 자체가 클라우드 역할입니다 (`58.29.21.11` 공인 IP + Tailscale `100.118.222.61`).
외부에서 휴대폰/노트북/태블릿/다른 PC로 접속해 같은 Claude 세션을 이어갈 수 있습니다.

## TL;DR

| 어디서? | 방법 | 셋업 시간 |
|---------|------|----------|
| 휴대폰 | 텔레그램 봇 메시지 | 0분 (이미 셋업됨) |
| 노트북/PC | Tailscale SSH + tmux attach | 5분 |
| VPN 없는 외부 | 공인 IP SSH + tmux attach | 키 등록만 |
| 브라우저 | claude.ai/code (별도 세션) | — |

## 0. 서버 측 — 한 번만 실행

서버에서 영속 세션을 띄워둡니다 (이 컴퓨터, Jun.AI 서버):

```bash
cd /home/issacs/work/quarkers/ortho-bender/.claude/worktrees/gracious-dijkstra-e6f145
./tools/launch-claude.sh
# 세션 생성 + attach. Ctrl+B → D 로 detach (세션은 백그라운드 유지)
```

이후로는 이 서버에서 `tmux attach -t ortho-bender` 만 치면 같은 세션으로 복귀.

## 1. 휴대폰 — 텔레그램 (가장 편함)

### 셋업 (이미 다 됨)
- Jun.AI Dashboard 텔레그램 봇 + 브릿지 작동 중
- ortho-bender 프로젝트에 `telegram@claude-plugins-official` v0.0.6 설치/enable 완료

### 사용법
1. 휴대폰에서 Jun.AI 텔레그램 봇과 채팅
2. ortho-bender 프로젝트 메시지 전송
3. Claude 세션이 응답 → 텔레그램으로 회신

* 매뉴얼 URL: 대시보드 → ortho-bender 프로젝트 → 채팅 패널

## 2. Tailscale (가장 안전, 추천 ⭐)

### 외부 머신 1회 셋업
**Linux/macOS:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# 브라우저 인증 → issacs0423 계정 로그인
```

**Windows:** https://tailscale.com/download/windows
**iOS/Android:** App Store / Play Store

### 접속
```bash
ssh issacs@100.118.222.61
# 또는 호스트명으로 (Tailscale MagicDNS)
ssh issacs@ubuntu

# 같은 세션 attach
tmux attach -t ortho-bender
```

### Tailscale SSH 더 편한 방법
서버에서:
```bash
sudo tailscale up --ssh
```
→ 외부 머신에서 `tailscale ssh issacs@ubuntu` 만 치면 키 없이도 접속 (Tailscale 인증 사용).

## 3. 공인 IP SSH (VPN 없는 환경)

### 외부 머신에 SSH 키 등록 (1회)

**외부 머신에서 키 생성 (없으면):**
```bash
ssh-keygen -t ed25519 -C "phone-or-laptop-name"
# 그냥 Enter 눌러 기본 위치/passphrase 사용
```

**서버(여기)의 ~/.ssh/authorized_keys 에 외부 머신 공개키 추가:**
```bash
# 외부 머신에서 공개키 표시
cat ~/.ssh/id_ed25519.pub

# 서버에서 그 라인을 추가 (직접 SSH 접속 가능 시)
echo "ssh-ed25519 AAAA... user@machine" >> ~/.ssh/authorized_keys

# 또는 외부 머신에서 한 번 비밀번호로 들어와서 ssh-copy-id
ssh-copy-id issacs@58.29.21.11
```

### 접속
```bash
ssh issacs@58.29.21.11
tmux attach -t ortho-bender
```

### 보안 권장
- `PasswordAuthentication no` (키만 허용)
- `fail2ban` 설치
- 가능하면 비표준 포트 사용

## 4. claude.ai/code 웹 (별도 세션)

같은 레포에서 별개 Claude 세션 시작:
1. https://claude.ai/code 로그인
2. 프로젝트 추가 → Git URL: `https://github.com/issacs83/ortho-bender.git`
3. 브랜치 `claude/gracious-dijkstra-e6f145`

⚠️ 이 서버의 tmux 세션과는 별개입니다. 대화 히스토리 공유 안 됨.
다만 메모리(`AGENT_MEMORY/`)는 git으로 공유되므로 핵심 컨텍스트는 자동 로드.

## 외부에서 새 워크트리에서 시작 (다른 컴퓨터)

```bash
git clone https://github.com/issacs83/ortho-bender.git
cd ortho-bender
git checkout claude/gracious-dijkstra-e6f145
./tools/setup-agent-memory.sh    # Claude 메모리 심볼릭 링크
./tools/launch-claude.sh          # tmux + Claude 시작
```

## Cheatsheet

```bash
# 서버 들어가기 (Tailscale)
ssh issacs@100.118.222.61

# 세션 들어가기
tmux attach -t ortho-bender

# 세션 빠져나오기 (세션은 유지)
Ctrl+B  D

# 세션 목록
tmux ls

# 세션 죽이기
tmux kill-session -t ortho-bender

# 새 세션 시작
./tools/launch-claude.sh
```

## 트러블슈팅

| 증상 | 원인 / 해결 |
|------|------------|
| `ssh: Permission denied (publickey,password)` | 외부 머신 공개키를 서버 authorized_keys에 추가 |
| `tmux: no sessions` | `./tools/launch-claude.sh` 로 새 세션 시작 |
| 텔레그램 봇 응답 없음 | dashboard 서비스 상태 확인 (`systemctl status claude-dev-forge` 또는 `pm2 list`) |
| Tailscale 연결 안 됨 | `sudo tailscale status` / `sudo tailscale up` |
| Claude 세션 멈춤 | `tmux kill-session -t ortho-bender` 후 재시작 |
