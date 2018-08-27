setenv mmcnum 0
setenv mmcpart 1
setenv mmctype ext2
setenv bootargs init=/init.sh rw earlycon console=tty0 console=ttyS0,115200 console=ttyS1,115200 console=ttyS2,115200

echo Loading kernel
ext2load mmc 0 0x42000000 uImage-postmarketos-allwinner
echo Loading device tree
ext2load mmc 0 0x43000000 postmarketos-allwinner.dtb
echo Booting kernel
bootm 0x42000000 - 0x43000000
