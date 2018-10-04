class DeviceInfo:
    def __init__(self):
        # Device
        self.code = None
        self.name = None
        self.manufacturer = None
        self.date = None
        self.keyboard = False
        self.keymaps = []
        self.nonfree = None
        self.dtb = None
        self.modules_initramfs = []
        self.external_storage = False
        self.flash_method = "none"
        self.arch = None
        self.dev_touchscreen = None
        self.dev_touchscreen_calibration = None
        self.dev_keyboard = None
        self.swap_size_recommended = None
        self.disable_dhcpd = False

        # Flash
        self.flash_offset_kernel = None
        self.flash_offset_ramdisk = None
        self.flash_offset_second = None
        self.flash_offset_tags = None
        self.flash_offset_base = None
        self.flash_pagesize = None
        self.flash_sparse = None
        self.flash_fastboot_vendor_id = None
        self.flash_fastboot_max_size = None
        self.kernel_cmdline = None
        self.bootimg_blobpack = False
        self.bootimg_qcdt = False
        self.generate_bootimg = False
        self.generate_legacy_uboot_initfs = False
        self.heimdall_partition_kernel = "KERNEL"
        self.heimdall_partition_initfs = "RECOVERY"
        self.heimdall_partition_system = "SYSTEM"

        # Weston
        self.weston_pixman_type = None

        # Splash
        self.screen_width = None
        self.screen_height = None

    def __repr__(self):
        return '<DeviceInfo {}>'.format(self.code)
