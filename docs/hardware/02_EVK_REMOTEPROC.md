# i.MX8MP EVK Remoteproc Analysis Report

Date: 2026-02-18
Source: EVK bring-up workspace (quarkers/workspace/)

---

## 1. Problem Summary

- `echo start > /sys/class/remoteproc/remoteproc0/state` causes hard lock / network loss
- Symptoms: `RC=124`, `EVK_DOWN`, FT4232 forced recovery required
- Failure point: very early in remoteproc boot path (right after `powering up`)

## 2. Root Cause Analysis

### Candidates investigated
1. Resource table mismatch
2. Memory map / TCM access issues
3. Peripheral ownership conflict (A53 vs M7)
4. prepare/start ordering
5. M7 core/domain clock gating

### Key finding: peripheral conflict
- `UART2` (Linux console) — **strong conflict**
- `SDMA1/3` — **conflict candidate**
- `I2C1/2` — conflict candidate
- `GPIO1~5` — conflict candidate (pinmux/IRQ contention)
- `MU` — required shared resource (normal)

### Conflict matrix

| Resource | M7 Candidate | A53 Status | Verdict |
|----------|-------------|------------|---------|
| MU | Required | `30aa0000.mailbox -> imx_mu` | Normal (shared) |
| UART1 | Candidate | `30860000.serial -> imx-uart` (active) | Conflict |
| UART2 | Candidate | `30890000.serial -> imx-uart` (console) | **Strong conflict** |
| UART3 | Candidate | Inactive | Low |
| UART4 | Candidate | Inactive | Low |
| I2C1 | Candidate | `30a20000.i2c -> imx-i2c` (active) | Conflict |
| I2C2 | Candidate | `30a30000.i2c -> imx-i2c` (active) | Conflict |
| I2C3~6 | Candidate | Inactive | Low |
| SDMA1 | Candidate | `30bd0000.dma-controller` (active) | **Conflict** |
| SDMA3 | Candidate | `30e10000.dma-controller` (active) | **Conflict** |
| GPIO1~5 | Candidate | All `gpio-mxc` active | **Conflict** |

### Resolution
- `clk_ignore_unused` alone did NOT fix the issue
- Final success achieved with proper sequencing (stop before start, correct firmware path)

## 3. RPMSG Safe Rules

### Hard rule
Use **only one** M7 control path per boot session:
1. **U-Boot path** (`bootaux`) — OR —
2. **Linux path** (`remoteproc` with rpmsg DTB)

**Never combine both in one boot session.**

### extlinux policy
- `nfs-safe` / `emmc-safe`: `FDT /imx8mp-evk.dtb` (no rpmsg, default)
- `nfs-rpmsg` / `emmc-rpmsg`: `FDT /imx8mp-evk-rpmsg.dtb`

### Test matrix
1. **Safe baseline**: Boot `nfs-safe`, verify `remoteproc0=offline`
2. **Linux remoteproc**: Boot `nfs-rpmsg`, do NOT `bootaux`, test via sysfs
3. **U-Boot bootaux**: Use `bootaux` in U-Boot, do NOT boot with rpmsg DTB

## 4. Successful Execution Procedure

```bash
echo stop > /sys/class/remoteproc/remoteproc0/state || true
echo imx8mp_m7_TCM_hello_world.elf > /sys/class/remoteproc/remoteproc0/firmware
echo start > /sys/class/remoteproc/remoteproc0/state
cat /sys/class/remoteproc/remoteproc0/state
```

Expected output:
- `STATE:running`
- dmesg: `remote processor imx-rproc is now up`

## 5. Kernel Patches Applied (EVK phase)

| Patch | Purpose |
|-------|---------|
| `0003-clk-imx8m-keep-m7_core-gate-disabled...` | Prevent clock gating during rproc start |
| `0004-remoteproc-imx-rproc-add-startup-tracepoints` | Debug trace in `imx_rproc_start()` |
| `0005-remoteproc-core-add-boot-path-markers` | `rproc_fw_boot` / `rproc_start` markers |
| `0006-arm64-dts-imx8mp-evk-rpmsg-add-power-domain` | Power domain experiment for CM7 |

## 6. Lessons Learned

- Never mix `bootaux` and Linux `remoteproc` in same boot session
- Always have FT4232 auto-recovery script ready for hard lock experiments
- Use Yocto patch-first approach instead of one-off dtc roundtrip edits
- Preserve success/failure logs in timestamped folders for regression comparison
- Peripheral ownership conflicts are more impactful than resource_table format issues
