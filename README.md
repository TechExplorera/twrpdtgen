# twrpdtgen

[![PyPi version](https://img.shields.io/pypi/v/twrpdtgen)](https://pypi.org/project/twrpdtgen/)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/ae7d7a75522b4d079c497ff6d9e052d1)](https://www.codacy.com/gh/twrpdtgen/twrpdtgen/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=twrpdtgen/twrpdtgen&amp;utm_campaign=Badge_Grade)

Create a ready-to-build [TWRP](https://twrp.me/) device tree only from an Android recovery image (or a boot image if the device has no recovery partition) of your device's stock ROM.

The generated tree is AOSP-style (`twrp_<codename>.mk`, `vendor/twrp`) and targets TWRP's
[minimal manifest](https://github.com/minimal-manifest-twrp/platform_manifest_twrp_aosp) (twrp-12.1 and newer).
It handles A/B and Virtual A/B, dynamic partitions (super), recovery-as-boot, boot header v0-v4,
FBE/metadata encryption flags, LZ4 ramdisks and AVB, all detected from the image.

Requires Python 3.9 or greater

## Installation

```sh
pip3 install twrpdtgen
```

Linux only: Be sure to have cpio installed in your system (Install cpio using `sudo apt install cpio` or `sudo pacman -S cpio` based on what package manager you're using)

## Instructions

```sh
python3 -m twrpdtgen <path to image>
```

When an image is provided, if everything goes well, there will be a device tree at `output/manufacturer/codename`

Options:

| Option | Description |
|---|---|
| `-o`, `--output` | Output folder (default: `output`) |
| `--super-size BYTES` | Real size of the super partition (`adb shell blockdev --getsize64 /dev/block/by-name/super`). Without it a placeholder is used |
| `--git` | Create a git repo with an initial commit |
| `-d`, `--debug` | Verbose logging |

The generated tree contains:

```
device/<manufacturer>/<codename>/
├── Android.bp / Android.mk
├── AndroidProducts.mk          # lunch twrp_<codename>-eng
├── BoardConfig.mk
├── device.mk
├── twrp_<codename>.mk
├── recovery.fstab
├── prebuilt/                   # kernel, dtb, dtbo
├── recovery/root/              # init .rc files from the stock recovery
└── README.md                   # build instructions for this device
```

Then build it with:

```sh
. build/envsetup.sh
lunch twrp_<codename>-eng
mka recoveryimage   # or `mka bootimage` if the device has no recovery partition
```

You can also use the module in a script, with the following code:

```python
from twrpdtgen.device_tree import DeviceTree

# Get image info
device_tree = DeviceTree(image_path, super_partition_size=None)

# Dump device tree to folder
device_tree.dump_to_folder(output_path)
```

## License

```
#
# Copyright (C) 2022 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#
```
