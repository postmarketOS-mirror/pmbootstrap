setenv mmcnum 0
setenv mmcpart 1
setenv mmctype ext2
setenv bootargs init=/init.sh rw earlycon console=tty0 console=ttyS0,115200

echo Loading kernel
ext2load mmc 0 0x48000000 uImage-postmarketos-stable
echo Loading device tree
ext2load mmc 0 0x49000000 postmarketos-stable.dtb
echo Loading initramfs
ext2load mmc 0 0x50000000 uInitrd-postmarketos-stable
echo Booting kernel
bootm 0x48000000 0x50000000 0x49000000

