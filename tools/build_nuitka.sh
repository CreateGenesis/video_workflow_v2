#!/bin/sh
# Compile a standalone cvgen binary for the machine running this script.
# Linux builds should use an Ubuntu 20.04 container so the result needs only glibc 2.31.
# macOS and Windows builds run on those systems, including GitHub Actions.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
case "$(uname -s)" in
  Linux) PLATFORM=linux; NAME=cvgen ;;
  Darwin) PLATFORM=macos; NAME=cvgen ;;
  MINGW*|MSYS*|CYGWIN*) PLATFORM=windows; NAME=cvgen.exe ;;
  *) echo "不支持的系统：$(uname -s)" >&2; exit 1 ;;
esac
OUT="$ROOT/tools/bin/$PLATFORM"
mkdir -p "$OUT"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install nuitka ordered-set zstandard -r tools/requirements-cli.txt
"$PYTHON" -m nuitka \
  --onefile \
  --assume-yes-for-downloads \
  --remove-output \
  --lto=yes \
  --python-flag=no_docstrings \
  --python-flag=no_asserts \
  --python-flag=-OO \
  --static-libpython=no \
  --include-package-data=certifi \
  --nofollow-import-to=pytest \
  --nofollow-import-to=unittest \
  --nofollow-import-to=setuptools \
  --nofollow-import-to=pip \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=xmlrpc \
  --nofollow-import-to=pydoc \
  --nofollow-import-to=doctest \
  --nofollow-import-to=lib2to3 \
  --noinclude-pytest-mode=nofollow \
  --noinclude-setuptools-mode=nofollow \
  --noinclude-unittest-mode=nofollow \
  --output-filename="$NAME" \
  --output-dir="$OUT" \
  cli/cvgen.py
echo "$OUT/$NAME"
