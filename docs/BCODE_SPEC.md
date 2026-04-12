# B-code Specification

Ortho-Bender 와이어 벤딩머신의 저수준 모션 포맷. 3D 와이어 형상을 순차적인
**피드 → 회전 → 벤드** 3단계 프리미티브 나열로 표현합니다.

---

## 1. 개념

각 B-code 스텝은 와이어를 만들기 위한 1회의 "삼박자" 동작입니다:

```
1. FEED:   와이어를 L mm 앞으로 밀어냄
2. ROTATE: 와이어를 β° 회전 (축 방향 torsion)
3. BEND:   벤딩 다이를 θ° 접어 와이어를 굽힘
```

이 세 동작을 순차적으로 N번 반복하면 임의의 3D 곡선을 생성할 수 있습니다.

---

## 2. 스텝 구조

각 스텝은 3개의 부동소수점 값으로 정의됩니다:

| 필드 | 단위 | 범위 | 의미 |
|------|------|------|------|
| `L_mm` | mm | `0.5` ~ `200.0` | 피드 길이 (와이어 선형 이송량) |
| `beta_deg` | ° | `-360.0` ~ `+360.0` | 와이어 축 회전각 (부호: 우회전 +) |
| `theta_deg` | ° | `0.0` ~ `180.0` | 벤드각 (스프링백 보정 전 raw) |

### JSON 표현
```json
{ "L_mm": 10.0, "beta_deg": 45.0, "theta_deg": 30.0 }
```

### IPC 바이너리 (`<fff>`, 12 바이트)
```
offset  type   field
0       f32    L_mm       (little-endian)
4       f32    beta_deg
8       f32    theta_deg
```

---

## 3. 좌표계 및 부호

### 3.1 머신 좌표계
- **원점**: 벤딩 다이 중심 (홈 포지션)
- **X+**: 피드 방향 (와이어가 나가는 쪽)
- **Y+**: 벤드 평면 (다이가 접히는 방향)
- **Z+**: 상방

### 3.2 회전 부호 규약
- **beta_deg**: 와이어를 피드 방향에서 보았을 때 **시계방향 +**
- **theta_deg**: 항상 ≥ 0 (방향은 직전 beta 로 결정)

### 3.3 스텝 간 관계
연속된 두 스텝 `s[i]`, `s[i+1]` 에 대해:
- `s[i+1].beta_deg` = 이전 굽힘 평면 대비 **상대 회전**
- 첫 스텝의 `beta_deg` 는 머신 원점 기준 절대값

---

## 4. 시퀀스 제약

| 제약 | 값 | 이유 |
|------|----|------|
| 최대 스텝 수 | **128** | M7 펌웨어 버퍼 크기 |
| 최소 피드 | `L_mm ≥ 0.5` | 드라이브 롤러 슬립 방지 |
| 최대 피드 | `L_mm ≤ 200.0` | 롤 지름 제한 |
| 최대 벤드 | `θ ≤ 180°` | 다이 기계적 한계 |
| 스프링백 후 θ | 180° 클램프 | 안전 |

128 스텝 초과 시 API 는 초과분을 잘라내고 warning 을 반환합니다.

---

## 5. 스프링백 보상

벤드 후 와이어는 탄성 복원되어 θ 가 실제보다 작게 나옵니다. 이를 보상하기 위해
**재질별 계수**를 곱해서 실제 명령 각도를 증가시킵니다.

```
θ_command = min(θ_input × factor[material], 180°)
```

| Material | Factor | 설명 |
|----------|--------|------|
| `0 = SS_304` | `×1.10` | Stainless Steel — 10% overbend |
| `1 = NITI` | `×1.35` | NiTi superelastic — 35% overbend |
| `2 = BETA_TI` | `×1.15` | TMA (Beta-Titanium) — 15% |
| `3 = CU_NITI` | `×1.30` | Cu-NiTi 열활성 — 30% |

자세한 재질 특성은 [`WIRE_MATERIALS.md`](WIRE_MATERIALS.md) 참고.

API 호출:
```bash
curl -X POST http://localhost:8000/api/bending/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "steps": [...],
    "material": 1,
    "wire_diameter_mm": 0.457
  }'
```

`material` 필드가 스프링백 계수를 결정합니다.
`apply_springback=false` (CAM API 에만 존재) 로 보상을 끌 수 있습니다 — 디버그 전용.

---

## 6. CAM 파이프라인과의 관계

3D 와이어 센터라인 폴리라인이 있는 경우 저수준 B-code 를 직접 작성할 필요 없이
`/api/cam/generate` 를 사용하면 자동으로 변환됩니다:

```
3D 폴리라인 (N 정점)
    │
    ▼  /api/cam/generate
이산화 + 방향벡터 계산
    │
    ▼
세그먼트별 (L, β, θ) 추출
    │
    ▼
스프링백 보상
    │
    ▼
B-code 스텝 배열 (N-2 벤드 + 1 tail feed)
```

자세한 알고리즘은 `src/app/server/services/cam_service.py` 참고.

---

## 7. 예제

### 7.1 직선 + 한번의 벤드
```json
{
  "steps": [
    { "L_mm": 20.0, "beta_deg": 0.0,  "theta_deg": 0.0 },
    { "L_mm": 20.0, "beta_deg": 0.0,  "theta_deg": 90.0 }
  ],
  "material": 0,
  "wire_diameter_mm": 0.457
}
```
→ 20 mm 직선 → 90° 벤드 → 20 mm 직선

### 7.2 3D 헬릭스 (2턴)
```json
{
  "steps": [
    { "L_mm": 5.0, "beta_deg": 30.0,  "theta_deg": 15.0 },
    { "L_mm": 5.0, "beta_deg": 30.0,  "theta_deg": 15.0 },
    { "L_mm": 5.0, "beta_deg": 30.0,  "theta_deg": 15.0 },
    ... (24개 반복)
  ]
}
```
→ 매 스텝 30° 회전 + 15° 벤드 로 나선을 형성

### 7.3 교정 아치와이어 (U-shape)
20 mm 직선 + 180° 아치 + 20 mm 직선:
```json
{
  "steps": [
    { "L_mm": 20.0, "beta_deg": 0.0, "theta_deg": 0.0 },
    { "L_mm": 3.0,  "beta_deg": 0.0, "theta_deg": 18.0 },
    { "L_mm": 3.0,  "beta_deg": 0.0, "theta_deg": 18.0 },
    ... (10회 반복하여 180°)
    { "L_mm": 20.0, "beta_deg": 0.0, "theta_deg": 0.0 }
  ],
  "material": 1,
  "wire_diameter_mm": 0.457
}
```

---

## 8. 검증 도구

B-code 를 실제로 구동하기 전에 검증할 수 있는 방법:

### 8.1 CAM 프리뷰 (권장)
```bash
curl -X POST http://localhost:8000/api/cam/generate -d '...' | jq .data
```
`max_bend_deg`, `total_length_mm`, `warnings` 를 확인.

### 8.2 Mock 모드 시뮬레이션
```bash
OB_MOCK_MODE=true python3 -m uvicorn server.main:app
```
실제 모터 없이 position/velocity 가 갱신되어 `/ws/motor` 로 진행률을 관찰할 수 있습니다.
자세한 내용은 [`MOCK_MODE.md`](MOCK_MODE.md) 참고.

### 8.3 프론트엔드 3D 뷰어
`src/app/frontend/` React 앱에서 B-code 를 시각화합니다.

---

## 9. 참고 구현

| 파일 | 역할 |
|------|------|
| `src/app/server/services/cam_service.py` | Python CAM (SDK 경로) |
| `src/app/cam/cam_engine.cpp` | C++ CAM (production 경로) |
| `src/firmware/source/motion/motion_task.c` | M7 B-code 실행기 |
| `src/shared/ipc_protocol.h` | RPMsg 메시지 구조체 |
| `src/app/server/models/schemas.py` | Pydantic `BcodeStep` |

---

## 10. 향후 확장

- **G-code 임포트**: CAD/CAM 툴 호환성 (Phase 2)
- **온도 프로파일**: NiTi 열활성 시퀀스 (Phase 2)
- **조건부 벤드**: 센서 피드백 기반 적응 제어 (Phase 3)
- **압력 피드백**: 변형률 측정으로 실시간 스프링백 보정 (연구 중)
