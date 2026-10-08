#!/usr/bin/env bash
# Kept for anyone following the v0.2 instructions. Same as: ../install.sh --uninstall
exec "$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)/install.sh" --uninstall
