#!/usr/bin/env bash
# markvault/ 폴더를 Anki 가 설치할 수 있는 .ankiaddon(zip) 으로 묶는다
set -e
cd "$(dirname "$0")"
mkdir -p dist
rm -f dist/markvault.ankiaddon
(cd markvault && zip -qr ../dist/markvault.ankiaddon . -x "*.pyc" -x "__pycache__/*" -x "user_files/state.json")
echo "dist/markvault.ankiaddon 생성"
