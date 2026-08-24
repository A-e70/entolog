#!/usr/bin/env bash
# Build a single-file entolog.pyz that runs on any machine with Python 3.9+
# and nothing installed. Copy it to a laptop, run: python3 entolog.pyz photos/
set -euo pipefail
cd "$(dirname "$0")"
rm -rf build dist && mkdir -p build dist
cp -r entolog build/
printf 'import sys\nfrom entolog.cli import main\nsys.exit(main())\n' > build/__main__.py
python3 -m zipapp build -o dist/entolog.pyz -p '/usr/bin/env python3'
chmod +x dist/entolog.pyz
rm -rf build
echo "dist/entolog.pyz  $(du -h dist/entolog.pyz | cut -f1)"
