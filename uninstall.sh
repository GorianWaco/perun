#!/usr/bin/env bash
# Odinstalowanie Perun
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh" --uninstall "$@"
