#!/bin/bash
#
# Copyright (C) 2026 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#
# Download a recovery/boot image and unwrap it if needed.
#
# Usage: fetch_image.sh <url> <output image path>
#
# Accepted inputs: a raw .img, .img.lz4, .img.gz, .img.xz, or a .zip/.tar/.tar.md5
# (e.g. a Samsung AP tar) containing recovery.img or boot.img (optionally .lz4).
#

set -euo pipefail

URL="${1:?Usage: fetch_image.sh <url> <output image path>}"
OUTPUT="${2:?Usage: fetch_image.sh <url> <output image path>}"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR:?}"' EXIT

log() { echo "[fetch_image] $*" >&2; }

is_android_image() {
	# boot/recovery images start with ANDROID!, vendor_boot with VNDRBOOT
	local magic
	magic="$(head -c 8 "$1" 2>/dev/null | tr -d '\0' || true)"
	[ "$magic" = "ANDROID!" ] || [ "$magic" = "VNDRBOOT" ]
}

decompress() {
	# Decompress $1 in place if it's compressed, print the resulting path
	local file="$1"
	local type
	type="$(file -b "$file")"
	case "$type" in
		*LZ4*)
			log "Decompressing LZ4: $(basename "$file")"
			lz4 -q -d -f "$file" "${file}.out"
			mv "${file}.out" "$file"
			;;
		*gzip*)
			log "Decompressing gzip: $(basename "$file")"
			gzip -dc "$file" > "${file}.out"
			mv "${file}.out" "$file"
			;;
		*XZ*)
			log "Decompressing xz: $(basename "$file")"
			xz -dc "$file" > "${file}.out"
			mv "${file}.out" "$file"
			;;
	esac
	echo "$file"
}

find_image_in() {
	# Prefer recovery over boot
	local dir="$1" name
	for name in recovery.img recovery.img.lz4 boot.img boot.img.lz4 init_boot.img init_boot.img.lz4; do
		local found
		found="$(find "$dir" -type f -name "$name" | head -n 1)"
		if [ -n "$found" ]; then
			echo "$found"
			return 0
		fi
	done
	return 1
}

log "Downloading image..."
curl -fL --retry 3 --retry-delay 5 --connect-timeout 30 -o "$WORK_DIR/input" "$URL"
log "Downloaded $(stat -c%s "$WORK_DIR/input") bytes"

FILE="$(decompress "$WORK_DIR/input")"

if ! is_android_image "$FILE"; then
	TYPE="$(file -b "$FILE")"
	mkdir -p "$WORK_DIR/extract"
	case "$TYPE" in
		*Zip*)
			log "Extracting zip archive..."
			unzip -q -o "$FILE" -d "$WORK_DIR/extract"
			;;
		*tar*)
			log "Extracting tar archive..."
			tar -xf "$FILE" -C "$WORK_DIR/extract"
			;;
		*)
			echo "Error: unsupported file type: $TYPE" >&2
			echo "Expected an Android boot/recovery image or an archive containing one." >&2
			echo "Make sure the URL is a direct download link (not an HTML download page)." >&2
			exit 1
			;;
	esac

	# Archives can be nested (e.g. a firmware zip containing an AP tar)
	for nested in $(find "$WORK_DIR/extract" -type f \( -name "*.tar" -o -name "*.tar.md5" \)); do
		log "Extracting nested tar: $(basename "$nested")"
		tar -xf "$nested" -C "$WORK_DIR/extract" --wildcards \
			'recovery.img*' 'boot.img*' 'init_boot.img*' 2>/dev/null || true
		rm -f "$nested"
	done

	if ! FILE="$(find_image_in "$WORK_DIR/extract")"; then
		echo "Error: no recovery.img or boot.img found in the archive" >&2
		exit 1
	fi
	log "Found $(basename "$FILE")"
	FILE="$(decompress "$FILE")"
fi

if ! is_android_image "$FILE"; then
	echo "Error: the file is not an Android boot/recovery image" >&2
	exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
mv "$FILE" "$OUTPUT"
log "Image ready: $OUTPUT"
