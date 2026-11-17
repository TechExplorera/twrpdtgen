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

## Using it from GitHub Actions

No local setup needed: fork this repository, then go to **Actions → Generate TWRP device tree → Run workflow**.

1. Upload your stock `recovery.img` (or `boot.img` if the device has no recovery partition) somewhere that gives a **direct download link**, e.g.:

   ```sh
   curl -T recovery.img https://<your-uploader>/recovery.img
   ```

   The workflow also accepts `.img.lz4`, `.img.gz`/`.xz`, `.zip` and `.tar`/`.tar.md5` archives (e.g. a Samsung `AP_*.tar.md5`), and picks `recovery.img` (or `boot.img`) from them.

2. Fill in the inputs:

   | Input | Description |
   |---|---|
   | `image_url` | Direct link to the image or archive |
   | `super_size` | Optional: super partition size in bytes (`adb shell blockdev --getsize64 /dev/block/by-name/super`) |
   | `build_twrp` | Also build TWRP with the generated tree (1-2 hours) |
   | `twrp_branch` | Minimal manifest branch used for the build (`twrp-12.1` or `twrp-14.1`) |

3. When it finishes you get:
   - a **release** with `twrp_device_<manufacturer>_<codename>.tar.gz`. Extract it in the root of your TWRP source to get `device/<manufacturer>/<codename>`;
   - the tree as a workflow **artifact**, plus a summary with the file list and `BoardConfig.mk`;
   - if `build_twrp` is enabled, the built `recovery.img`/`boot.img` attached to the same release (plus an Odin `.tar` for Samsung).

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
