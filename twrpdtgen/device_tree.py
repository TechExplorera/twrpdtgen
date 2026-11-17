#
# Copyright (C) 2022 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#

from datetime import datetime
from git import Repo
from pathlib import Path
from sebaubuntu_libs.libaik import AIKManager
from sebaubuntu_libs.libandroid.device_info import DeviceInfo
from sebaubuntu_libs.libandroid.fstab import Fstab, FstabEntry
from sebaubuntu_libs.libandroid.props import BuildProp
from sebaubuntu_libs.liblogging import LOGD, LOGW
from shutil import copyfile, rmtree
from twrpdtgen import __version__ as version
from twrpdtgen.templates import render_template
from typing import Optional

BUILDPROP_LOCATIONS = [Path() / "default.prop",
                       Path() / "prop.default",]
BUILDPROP_LOCATIONS += [Path() / dir / "build.prop"
                        for dir in ["system", "vendor"]]
BUILDPROP_LOCATIONS += [Path() / dir / "etc" / "build.prop"
                        for dir in ["system", "vendor"]]

FSTAB_LOCATIONS = [Path() / "etc" / "recovery.fstab"]
FSTAB_LOCATIONS += [Path() / dir / "etc" / "recovery.fstab"
                    for dir in ["system", "vendor"]]

INIT_RC_LOCATIONS = [Path()]
INIT_RC_LOCATIONS += [Path() / dir / "etc" / "init"
                      for dir in ["system", "vendor"]]

# Placeholder super partition size, used when the user doesn't provide one
DEFAULT_SUPER_PARTITION_SIZE = 9126805504

# Space reserved by liblp for metadata in the super partition
SUPER_METADATA_RESERVED_SIZE = 4 * 1024 * 1024

# Logical partitions that need TARGET_COPY_OUT_* to be set
COPY_OUT_PARTITIONS = ["system_ext", "product", "vendor", "odm",
                       "vendor_dlkm", "odm_dlkm", "system_dlkm"]

QCOM_PLATFORM_PREFIXES = ("msm", "sdm", "sm", "apq", "qcs", "qcm")
QCOM_PLATFORM_NAMES = {"atoll", "bengal", "crow", "holi", "kalama", "kona",
                       "lahaina", "lito", "parrot", "pineapple", "sun",
                       "taro", "trinket"}

class DeviceTree:
	"""
	A class representing a TWRP device tree

	It parses a recovery (or boot) image and generates an
	AOSP-style device tree buildable with TWRP's minimal manifest
	"""
	def __init__(self, image: Path, super_partition_size: Optional[int] = None):
		"""Initialize the device tree class."""
		self.image = image

		self.current_year = str(datetime.now().year)

		# Check if the image exists
		if not self.image.is_file():
			raise FileNotFoundError("Specified file doesn't exist")

		# Extract the image
		self.aik_manager = AIKManager()
		self.image_info = self.aik_manager.unpackimg(image)

		assert self.image_info.ramdisk, "Ramdisk not found"

		LOGD("Getting device infos...")
		self.build_prop = BuildProp()
		for build_prop in [self.image_info.ramdisk / location for location in BUILDPROP_LOCATIONS]:
			if not build_prop.is_file():
				continue

			self.build_prop.import_props(build_prop)

		self.device_info = DeviceInfo(self.build_prop)

		# Parse fstab
		fstab = None
		for fstab_location in [self.image_info.ramdisk / location for location in FSTAB_LOCATIONS]:
			if not fstab_location.is_file():
				continue

			LOGD(f"Generating fstab using {fstab_location} as reference...")
			fstab = Fstab(fstab_location)
			break

		if fstab is None:
			raise AssertionError("fstab not found")

		self.fstab = fstab

		# Search for init rc files
		self.init_rcs: list[Path] = []
		for init_rc_path in [self.image_info.ramdisk / location for location in INIT_RC_LOCATIONS]:
			if not init_rc_path.is_dir():
				continue

			self.init_rcs += [init_rc for init_rc in init_rc_path.iterdir()
			                  if init_rc.name.endswith(".rc") and init_rc.name != "init.rc"]

		self.tree = self._get_tree_config(super_partition_size)

	def _get_tree_config(self, super_partition_size: Optional[int]) -> dict:
		"""Compute all the values the templates need from the image, props and fstab."""
		device_info = self.device_info
		fstab = self.fstab

		header_version = int(self.image_info.header_version or 0)

		# A/B
		is_ab = bool(device_info.device_is_ab)
		has_recovery_partition = fstab.get_partition_by_mount_point("/recovery") is not None
		recovery_as_boot = is_ab and not has_recovery_partition

		ab_partitions: list[str] = []
		for entry in fstab.get_slotselect_partitions():
			name = Path(entry.mount_point).name if entry.mount_point != "/" else "system"
			if name and name not in ab_partitions:
				ab_partitions.append(name)
		for model in fstab.get_ab_partitions_models():
			if model.name not in ab_partitions:
				ab_partitions.append(model.name)

		# Dynamic partitions
		logical_partitions: dict[str, str] = {}
		for entry in fstab.get_logical_partitions():
			name = Path(entry.mount_point).name if entry.mount_point != "/" else "system"
			logical_partitions.setdefault(name, entry.fs_type)

		uses_dynamic_partitions = bool(device_info.device_uses_dynamic_partitions) or bool(logical_partitions)
		virtual_ab = bool(device_info.device_uses_virtual_ab)

		super_partition_size_is_known = super_partition_size is not None
		if super_partition_size is None:
			super_partition_size = DEFAULT_SUPER_PARTITION_SIZE

		if is_ab and not virtual_ab:
			# Legacy A/B dynamic partitions keep both slots in super
			super_group_size = super_partition_size // 2 - SUPER_METADATA_RESERVED_SIZE
		else:
			super_group_size = super_partition_size - SUPER_METADATA_RESERVED_SIZE

		# Encryption
		data_entry = fstab.get_partition_by_mount_point("/data")
		data_flags = data_entry.fs_flags if data_entry else []
		fbe_flag = self._get_flag(data_flags, "fileencryption")
		uses_fbe = fbe_flag is not None
		uses_fde = any(flag.split("=")[0] in ("forceencrypt", "encryptable", "forcefdeorfbe")
		               for flag in data_flags)
		uses_metadata_encryption = (self._get_flag(data_flags, "metadata_encryption") is not None
		                            or self._get_flag(data_flags, "keydirectory") is not None)
		has_metadata_partition = fstab.get_partition_by_mount_point("/metadata") is not None

		if fbe_flag is not None and fbe_flag.endswith(":v2"):
			fscrypt_policy = 2
		elif fbe_flag is not None and fbe_flag.endswith(":v1"):
			fscrypt_policy = 1
		else:
			fscrypt_policy = 2 if self._first_api_level() >= 30 else 1

		# Platform specific bits
		platform = (device_info.platform or "").lower()
		if platform.startswith(QCOM_PLATFORM_PREFIXES) or platform in QCOM_PLATFORM_NAMES:
			soc_vendor = "qcom"
		elif platform.startswith("mt"):
			soc_vendor = "mtk"
		elif platform.startswith(("exynos", "s5e", "universal", "erd")):
			soc_vendor = "samsung"
		else:
			soc_vendor = "generic"

		return {
			"header_version": header_version,
			"is_ab": is_ab,
			"ab_partitions": ab_partitions,
			"has_recovery_partition": has_recovery_partition,
			"recovery_as_boot": recovery_as_boot,
			"uses_dynamic_partitions": uses_dynamic_partitions,
			"virtual_ab": virtual_ab,
			"logical_partitions": logical_partitions,
			"copy_out_partitions": [p for p in COPY_OUT_PARTITIONS if p in logical_partitions],
			"super_partition_size": super_partition_size,
			"super_partition_size_is_known": super_partition_size_is_known,
			"super_group_name": f"{device_info.manufacturer}_dynamic_partitions",
			"super_group_size": super_group_size,
			"uses_crypto": uses_fbe or uses_fde,
			"uses_fbe": uses_fbe,
			"uses_metadata_encryption": uses_metadata_encryption,
			"has_metadata_partition": has_metadata_partition,
			"fscrypt_policy": fscrypt_policy,
			"soc_vendor": soc_vendor,
			"kernel_image_name": self._get_kernel_image_name(),
			"ramdisk_compression": (self.image_info.ramdisk_compression or "").lower(),
			"first_api_level": self._first_api_level(),
		}

	@staticmethod
	def _get_flag(flags: list[str], name: str) -> Optional[str]:
		for flag in flags:
			key, _, value = flag.partition("=")
			if key == name:
				return value
		return None

	def _first_api_level(self) -> int:
		try:
			return int(self.device_info.first_api_level)
		except (TypeError, ValueError):
			return 0

	def _get_kernel_image_name(self) -> str:
		kernel = self.image_info.kernel
		if kernel is None or not Path(kernel).is_file():
			return "Image"

		with open(kernel, "rb") as f:
			header = f.read(0x40)

		if header[:2] == b"\x1f\x8b":
			return "Image.gz"
		if header[:4] in (b"\x02\x21\x4c\x18", b"\x04\x22\x4d\x18"):
			return "Image.lz4"
		if header[0x38:0x3c] == b"ARMd":
			return "Image"
		if self.device_info.arch is not None and self.device_info.arch.bitness == 32:
			return "zImage"
		return "Image"

	def dump_to_folder(self, output_path: Path, git: bool = False) -> Path:
		device_tree_folder = output_path / self.device_info.manufacturer / self.device_info.codename
		prebuilt_path = device_tree_folder / "prebuilt"
		recovery_root_path = device_tree_folder / "recovery" / "root"

		LOGD("Creating device tree folders...")
		if device_tree_folder.is_dir():
			rmtree(device_tree_folder, ignore_errors=True)
		device_tree_folder.mkdir(parents=True)
		prebuilt_path.mkdir(parents=True)
		recovery_root_path.mkdir(parents=True)

		LOGD("Writing makefiles/blueprints")
		self._render_template(device_tree_folder, "Android.bp", comment_prefix="//")
		self._render_template(device_tree_folder, "Android.mk")
		self._render_template(device_tree_folder, "AndroidProducts.mk")
		self._render_template(device_tree_folder, "BoardConfig.mk")
		self._render_template(device_tree_folder, "device.mk")
		self._render_template(device_tree_folder, "twrp_device.mk", out_file=f"twrp_{self.device_info.codename}.mk")
		self._render_template(device_tree_folder, "README.md")

		LOGD("Copying kernel...")
		if self.image_info.kernel is not None:
			copyfile(self.image_info.kernel, prebuilt_path / "kernel")
		if self.image_info.dt is not None:
			copyfile(self.image_info.dt, prebuilt_path / "dt.img")
		if self.image_info.dtb is not None:
			copyfile(self.image_info.dtb, prebuilt_path / "dtb.img")
		if self.image_info.dtbo is not None:
			copyfile(self.image_info.dtbo, prebuilt_path / "dtbo.img")

		LOGD("Copying fstab...")
		# Keep the AOSP (v2) fstab format: TWRP parses it natively and it
		# preserves the fs_mgr flags (encryption, slotselect, logical, ...)
		(device_tree_folder / "recovery.fstab").write_text(self._format_fstab())

		LOGD("Copying init scripts...")
		for init_rc in self.init_rcs:
			copyfile(init_rc, recovery_root_path / init_rc.name, follow_symlinks=True)

		if self.tree["uses_dynamic_partitions"] and not self.tree["super_partition_size_is_known"]:
			LOGW("Super partition size unknown, a placeholder value was used. "
			     "Pass --super-size with the real size (in bytes) of your super partition.")

		if not git:
			return device_tree_folder

		# Create a git repo
		LOGD("Creating git repo...")

		git_repo = Repo.init(device_tree_folder)
		git_config_reader = git_repo.config_reader()
		git_config_writer = git_repo.config_writer()

		try:
			git_global_email, git_global_name = git_config_reader.get_value('user', 'email'), git_config_reader.get_value('user', 'name')
		except Exception:
			git_global_email, git_global_name = None, None

		if git_global_email is None or git_global_name is None:
			git_config_writer.set_value('user', 'email', 'barezzisebastiano@gmail.com')
			git_config_writer.set_value('user', 'name', 'Sebastiano Barezzi')

		git_repo.index.add(["*"])
		commit_message = self._render_template(None, "commit_message", to_file=False)
		git_repo.index.commit(commit_message)

		return device_tree_folder

	def _format_fstab(self) -> str:
		entries: list[FstabEntry] = self.fstab.entries
		columns = [(entry.src, entry.mount_point, entry.fs_type, ",".join(entry.mnt_flags))
		           for entry in entries]
		headers = ("#<src>", "<mnt_point>", "<type>", "<mnt_flags>")
		widths = [max(len(value) for value in column) + 4
		          for column in zip(headers, *columns)]

		def format_line(values, last):
			return ("".join(value.ljust(width) for value, width in zip(values, widths)) + last).rstrip()

		lines = [format_line(headers, "<fs_mgr_flags>")]
		for entry, values in zip(entries, columns):
			lines.append(format_line(values, ",".join(entry.fs_flags)))

		return "\n".join(lines) + "\n"

	def _render_template(self, *args, comment_prefix: str = "#", **kwargs):
		return render_template(*args,
		                       comment_prefix=comment_prefix,
		                       current_year=self.current_year,
		                       device_info=self.device_info,
		                       fstab=self.fstab,
		                       image_info=self.image_info,
		                       tree=self.tree,
		                       version=version,
		                       **kwargs)

	def cleanup(self):
		# Cleanup
		self.aik_manager.cleanup()
