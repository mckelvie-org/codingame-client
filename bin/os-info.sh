#!/usr/bin/env bash
# Sourced script that sets environment variables identifying the OS,
# Linux distribution, and preferred package manager.
#
# Usage: source bin/os-info.sh
#
# Variables set:
#   OS        — "macOS", "Linux", "Windows", or "UNKNOWN"
#   OS_DISTRO — distro ID from /etc/os-release (e.g. "ubuntu", "fedora"),
#               "macOS" / "Windows", or "UNKNOWN"
#   OS_LIKE   — normalised family: "debian", "fedora", "arch", "suse",
#               "macOS", "Windows", or "UNKNOWN"
#   OS_PM     — preferred package manager: "brew", "apt", "dnf", "yum",
#               "pacman", "zypper", "winget", or "UNKNOWN"

OS="UNKNOWN"
OS_DISTRO="UNKNOWN"
OS_LIKE="UNKNOWN"
OS_PM="UNKNOWN"

_uname="$(uname -s 2>/dev/null)"

case "$_uname" in
    Darwin)
        OS="macOS"
        OS_DISTRO="macOS"
        OS_LIKE="macOS"
        OS_PM="brew"
        ;;

    Linux)
        OS="Linux"

        if [[ -r /etc/os-release ]]; then
            # shellcheck source=/dev/null
            source /etc/os-release
            OS_DISTRO="${ID:-UNKNOWN}"

            # Normalise ID_LIKE (may be a space-separated list) to a single family.
            _like="${ID_LIKE:-${ID:-}}"
            case "$_like" in
                *debian*|*ubuntu*)  OS_LIKE="debian"  ;;
                *fedora*|*rhel*|*centos*|*rocky*|*alma*)
                                    OS_LIKE="fedora"  ;;
                *arch*)             OS_LIKE="arch"    ;;
                *suse*)             OS_LIKE="suse"    ;;
                *)                  OS_LIKE="UNKNOWN" ;;
            esac
        fi

        case "$OS_LIKE" in
            debian)
                OS_PM="apt"
                ;;
            fedora)
                if command -v dnf &>/dev/null; then
                    OS_PM="dnf"
                else
                    OS_PM="yum"
                fi
                ;;
            arch)
                OS_PM="pacman"
                ;;
            suse)
                OS_PM="zypper"
                ;;
        esac
        ;;

    MINGW*|MSYS*|CYGWIN*)
        OS="Windows"
        OS_DISTRO="Windows"
        OS_LIKE="Windows"
        if command -v winget &>/dev/null; then
            OS_PM="winget"
        elif command -v choco &>/dev/null; then
            OS_PM="choco"
        fi
        ;;
esac

unset _uname _like
