# Ortho-Bender Quick Start Card

인쇄용 1페이지 퀵 가이드. 보드 상자 윗면 또는 포장 내부에 동봉하세요.

---

```
╔══════════════════════════════════════════════════════════════════╗
║            ORTHO-BENDER — DEVELOPER HANDOVER KIT                 ║
║                                                                  ║
║  1. 전원 어댑터를 DC-Jack 에 연결                                ║
║  2. 전원 스위치 ON → LED 부팅 대기 (~60 초)                      ║
║  3. 노트북에서 WiFi 접속                                         ║
║        SSID : Ortho-Bender-FBAD                                  ║
║        PASS : ortho-bender                                       ║
║  4. 브라우저에서 접속                                            ║
║        http://192.168.4.1:8000/                                  ║
║        (또는  http://ortho-bender.local:8000/ )                  ║
║  5. SSH 개발 접속                                                ║
║        ssh root@192.168.4.1                                      ║
║        password: ortho-bender                                    ║
║                                                                  ║
║  >> 문서: 동봉된 PDF 01 / 02 / 03 참조                           ║
║  >> 복구: 동봉 USB + uuu, 부록 B 참조                            ║
║                                                                  ║
║  이슈 / 알려진 제약                                              ║
║    • 카메라는 J6 포트에 장착 (J7 미사용)                         ║
║    • 첫 WiFi Scan 은 7~8 초 소요 (정상)                          ║
║                                                                  ║
║  >> 운영 배포 전 반드시 root 비밀번호를 변경하고                 ║
║     SSH pubkey 전용으로 전환하세요 (개발 이관용 임시 자격)       ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 보드 라벨 텍스트 (상단 부착용)

```
Ortho-Bender EVK  v1.0
────────────────────────
WiFi : Ortho-Bender-FBAD
PASS : ortho-bender
URL  : http://192.168.4.1:8000/
SSH  : root @ 192.168.4.1
PW   : ortho-bender
```

크기 가이드: 50 mm × 25 mm 흰색 스티커, 검정 글자 8pt, 보드 상단 빈 공간(방열판 옆)에 부착.
