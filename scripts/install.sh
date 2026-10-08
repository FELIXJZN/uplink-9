#!/usr/bin/env bash
# Kept for anyone following the v0.2 instructions. The installer is ../install.sh now.
exec "$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)/install.sh" "$@"
