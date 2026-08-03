# U-Boot Boot Flow Scripts

Source: EVK bring-up workspace (quarkers/workspace/)

---

## Development Profile

Fast iteration: TFTP kernel/dtb + NFS root, fallback to local eMMC.

```
setenv boot_profile dev
setenv ipaddr 192.168.77.2
setenv serverip 192.168.77.1
setenv gatewayip 192.168.77.1
setenv netmask 255.255.255.0

setenv boot_nfs_tftp 'tftp ${loadaddr} imx8mp/Image; tftp ${fdt_addr_r} imx8mp/imx8mp-evk-rpmsg.dtb; setenv bootargs console=ttymxc1,115200 root=/dev/nfs nfsroot=${serverip}:/srv/nfs/imx8mp-rootfs,v3,tcp rw; booti ${loadaddr} - ${fdt_addr_r}'

setenv boot_emmc_local 'fatload mmc 2:1 ${loadaddr} Image; fatload mmc 2:1 ${fdt_addr_r} imx8mp-evk-rpmsg.dtb; setenv bootargs console=ttymxc1,115200 root=/dev/mmcblk2p2 rootwait rw; booti ${loadaddr} - ${fdt_addr_r}'

# NOTE: kernel ip= parameter removed from all profiles.
# eth0 static IP (192.168.77.2/24) is handled by systemd-networkd
# via /etc/systemd/network/10-eth0.network (installed by Yocto image).
# NFS boot uses serverip/ipaddr env vars set above (U-Boot TFTP uses those directly).

setenv boot_auto 'run boot_nfs_tftp || run boot_emmc_local'
```

## Production Profile

Conservative: eMMC only, A/B placeholder ready.

```
setenv boot_profile prod

# A/B slot placeholder (extend with signed FIT later)
# setenv active_slot a
# setenv fitfile_a imx8mp-prod-a.itb
# setenv fitfile_b imx8mp-prod-b.itb

setenv boot_emmc_local 'fatload mmc 2:1 ${loadaddr} Image; fatload mmc 2:1 ${fdt_addr_r} imx8mp-evk-rpmsg.dtb; setenv bootargs console=ttymxc1,115200 root=/dev/mmcblk2p2 rootwait rw; booti ${loadaddr} - ${fdt_addr_r}'

setenv boot_auto 'run boot_emmc_local'
```

## Notes

- Dev profile uses TFTP+NFS for rapid kernel/rootfs iteration without reflashing
- Prod profile will evolve to signed FIT image with A/B partitioning
- DTB selection: use `imx8mp-evk-rpmsg.dtb` for M7 remoteproc, `imx8mp-evk.dtb` for safe baseline
- See `../hardware/02_EVK_REMOTEPROC.md` for RPMSG safe rules
