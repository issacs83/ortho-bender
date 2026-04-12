# Wire Materials Reference

Ortho-Bender 가 지원하는 치과 교정 와이어 재질과 스프링백 특성.

---

## 1. 지원 재질

| ID | 이름 | 축약 | API `material` |
|----|------|------|----------------|
| 0 | Stainless Steel 304 | SS 304 | `0` |
| 1 | Nickel-Titanium | NiTi | `1` |
| 2 | Beta-Titanium | β-Ti (TMA) | `2` |
| 3 | Copper Nickel-Titanium | Cu-NiTi | `3` |

---

## 2. 기계적 특성 비교

| 재질 | 탄성계수 E (GPa) | 항복강도 (MPa) | 연신율 | 스프링백 |
|------|-----------------|----------------|--------|----------|
| SS 304 | ~180 | ~1400 | 중 | 중 (×1.10) |
| NiTi | ~40~80 (가변) | ~500 | 매우 높음 | 매우 높음 (×1.35) |
| β-Ti (TMA) | ~70 | ~1000 | 중-고 | 중 (×1.15) |
| Cu-NiTi | ~40 (@37°C) | ~500 | 매우 높음 | 높음 (×1.30) |

NiTi 계열은 **superelastic** 구간에서 탄성계수가 비선형이므로 단일 계수로 근사합니다.
실제 생산 경로에서는 NPU 기반 ML 모델이 온도/직경/이력 기반으로 동적 보정을 수행합니다.

---

## 3. 스프링백 계수 (현재 사용 중)

```
θ_command = min(θ_target × factor[material], 180°)
```

```python
_SPRINGBACK_FACTOR = {
    0: 1.10,   # SS_304
    1: 1.35,   # NITI
    2: 1.15,   # BETA_TI
    3: 1.30,   # CU_NITI
}
```

- 경험적 계수 (문헌 + 내부 실험)
- 모든 재질에서 **overbend 후 180° 로 클램프**
- `wire_diameter_mm` 은 현재 로그에만 사용; 향후 NPU 보정 입력 예정

참고 소스: `src/app/server/routers/bending.py`, `services/cam_service.py`

---

## 4. 임상 사용 가이드

### 4.1 SS 304
- **용도**: Finishing 단계, ligature wire, 보조 archwire
- **장점**: 저렴, 강성, 예측 가능한 벤드
- **단점**: 생체 적합성 중간, 표면 거칠음
- **직경**: 0.014"~0.020" (0.356~0.508 mm)

### 4.2 NiTi
- **용도**: Initial aligning, leveling (치료 초기)
- **장점**: superelastic → 일정한 저강도로 넓은 변위 흡수
- **주의**: 구부리기 어려움(벤딩머신 기준), 과열 시 오스테나이트 ↔ 마르텐사이트 상변태
- **직경**: 0.012"~0.018" (0.305~0.457 mm)
- **⚠️ 주의**: NiTi 벤딩 시 국부 온도 상승을 막기 위해 저속 벤딩 (bend rate < 10°/s) 권장

### 4.3 β-Titanium (TMA)
- **용도**: Space closure, finishing, intermediate 단계
- **장점**: 중간 강성, 용접 가능, 마찰 낮음
- **단점**: SS 대비 고가
- **직경**: 0.016"~0.019" (0.406~0.483 mm)

### 4.4 Cu-NiTi
- **용도**: Thermally activated — 구강 내 온도(37°C)에서 활성화
- **특징**: 상온(실험실)에서는 연성, 구강 내에서 회복력 발현
- **주의**: 벤딩머신 내 온도가 Af point 이하여야 함 (온도 관리 필요)

---

## 5. API 사용 예

### 5.1 SS 304 with 0.018" wire
```json
{
  "steps": [ ... ],
  "material": 0,
  "wire_diameter_mm": 0.457
}
```

### 5.2 NiTi with 0.016" wire
```json
{
  "steps": [ ... ],
  "material": 1,
  "wire_diameter_mm": 0.406
}
```

### 5.3 CAM generate with material auto-selection (프론트엔드 로직)
```ts
const material = selectMaterialFromPrescription(treatmentPlan);
const resp = await fetch("/api/cam/generate", {
  method: "POST",
  body: JSON.stringify({
    points: curve,
    material,
    wire_diameter_mm: 0.457,
    apply_springback: true,
  }),
});
```

---

## 6. 직경 변환표

| inch | mm | 용도 |
|------|-----|------|
| 0.012" | 0.305 | 초기 NiTi |
| 0.014" | 0.356 | 초기 NiTi / SS |
| 0.016" | 0.406 | 중간 NiTi / SS / TMA |
| 0.017" × 0.025" | 0.432 × 0.635 | 사각 와이어 (미지원) |
| 0.018" | **0.457** ⭐ | **표준** (기본 `wire_diameter_mm`) |
| 0.019" × 0.025" | 0.483 × 0.635 | 사각 (미지원) |
| 0.020" | 0.508 | 강성 finishing |

현재 지원: **원형 단면만** (사각 와이어는 Phase 3 이후).

---

## 7. 재질별 벤딩 파라미터 (권장값)

| 재질 | Max θ per step | Max bend rate | 비고 |
|------|----------------|---------------|------|
| SS 304 | 90° | 30°/s | 자유 |
| NiTi | 60° | 10°/s | 열 관리 필요 |
| β-Ti | 90° | 20°/s | 중간 |
| Cu-NiTi | 60° | 10°/s | 온도 Af 이하 유지 |

현재 SDK 는 이 권장값을 **강제하지 않습니다** — 호출자(CAM 또는 프론트엔드)가
입력 단계에서 검증하세요. 향후 버전에서 하드 가드 추가 예정.

---

## 8. 데이터 소스

- **EF 계수**: 내부 실험(25°C, 0.018" wire, 10회 평균)
- **재질 사양**: 제조사 datasheet
  - SS 304: ASTM A313
  - NiTi: ASTM F2063
  - β-Ti: ASTM F1295
- **임상 가이드**: Graber, Vanarsdall, Vig — *Orthodontics: Current Principles and Techniques*
- **ML 향상**: NPU 기반 springback 예측 모델 (학습 중)

---

## 9. 향후 로드맵

- [ ] NPU 기반 재질별 **동적** 스프링백 보정 (직경·온도·이력 입력)
- [ ] 사각 와이어 지원 (`wire_cross_section: "round" | "rect"`)
- [ ] 온도 프로파일 입력 (Cu-NiTi 열활성 시퀀스)
- [ ] 벤드 이력 기반 피로 예측 (파단 방지)
- [ ] 재질별 최대 θ / rate **강제 검증** 라우터
