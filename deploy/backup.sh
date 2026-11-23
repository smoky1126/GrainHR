#!/bin/bash
# Copy the payroll data folder to a dated backup. Keeps 30 days.
set -euo pipefail
src="${PAYROLL_HOME:?Set PAYROLL_HOME to the data folder}"
root="${GRAINHR_BACKUP:-$(dirname "$src")/backups}"
dest="$root/$(date +%Y-%m-%d)"
mkdir -p "$dest"
cp -a "$src/." "$dest/"
find "$root" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
echo "Backed up to $dest"
