---
name: Hardware Setup — Ortho-Bender 모터 테스트 벤치
description: 보드 액세스, USB, 시리얼, 모터 드라이버 하드웨어 셋업 정보
type: project
originSessionId: b5d1614f-af0f-4ed0-aa44-10f74e526594
---
# 하드웨어 셋업

## 보드 (i.MX8MP EVK)
- 시리얼 콘솔: `/dev/ttyUSB2` (FT4232H Channel C, 115200 8N1)
- 부팅 상태: NXP i.MX Release Distro 5.15-kirkstone, root@imx8mpevk
- minicom 캡처 로그: `/tmp/minicom.log` (사용자가 minicom -C로 캡처 중)

## USB FT4232H
- 4채널 (ttyUSB0~3 모두 매핑됨)
- ttyUSB2 = 시리얼 콘솔
- Channel A (`ftdi://ftdi:4232:1:4/1`) = JTAG + GPIO reset
  - nSRST = ADBUS5 (0x20), ONOFF_B = ADBUS7 (0x80)

## 모터 하드웨어 (테스트 벤치)
- 모터: 17HE15-1504S NEMA17 × 3축 (FEED, BEND, LIFT)
- 드라이버: DRI0035 (TMC260 기반) × 3
- 레벨 시프터: TXS0108E × 2 (1.8V ↔ 5V)
- PSU: LRS-35-12 (12V/3A/36W) — 추후 LRS-75-12 업그레이드
- 출력 측 1000µF/25V bulk cap 추가 필요

## SSH 접근 (보드 부팅 후)
- USB Ethernet: 192.168.77.2 (CDC ECM)
- WiFi AP: 192.168.4.1 (hostapd, 부팅 ~10s 후 활성)
- 우선순위: SSH USB > SSH WiFi AP > Serial

## How to apply
- 시리얼 명령 보낼 때: pyserial로 `/dev/ttyUSB2` 열고 → 명령 → close → `/tmp/minicom.log` tail로 응답 확인
- 보드 응답이 안 오면: SSH로 우회 (192.168.77.2)
- 보드 hang 시: FT4232H GPIO reset
