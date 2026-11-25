#!/bin/sh
# Xiaomi TV Tool — bản fix1.
# Khác bản gốc ở khâu cài đặt: giải nén vào thư mục tạm mới, kiểm tra xong
# mới thay bản đang dùng (bản cũ giữ ở ~/.xiaomi-tv-tool.bak), nên một lượt
# cập nhật lỗi không làm hỏng bản đang chạy và không trộn file cũ/mới.
set -eu
REPOSITORY=${1:-}
if ! printf '%s' "$REPOSITORY" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$'; then
  echo 'Cach dung: sh tv-start.sh TEN_GITHUB/xiaomi-tv-tool'
  exit 1
fi
if command -v pkg >/dev/null 2>&1; then
  if ! command -v python3 >/dev/null 2>&1 || ! command -v adb >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    pkg update -y
    pkg install -y python android-tools curl
  fi
elif command -v apk >/dev/null 2>&1; then
  if ! command -v python3 >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    apk update
    apk add python3 curl ca-certificates
  fi
  if ! command -v adb >/dev/null 2>&1; then
    apk add android-tools || apk add android-tools-adb
  fi
else
  echo 'Chay file nay trong Termux (Android) hoac iSH (iPhone).'
  exit 1
fi
command -v adb >/dev/null 2>&1 || { echo 'Chua cai duoc ADB; can kiem tra kho goi cua Termux/iSH.'; exit 1; }
INSTALL_DIR="$HOME/.xiaomi-tv-tool"
BACKUP_DIR="$HOME/.xiaomi-tv-tool.bak"
for p in "$INSTALL_DIR" "$BACKUP_DIR"; do
  if [ -L "$p" ]; then
    echo 'Thu muc cai dat/du phong la lien ket; dung de tranh thay nham du lieu.'
    exit 1
  fi
done
STAGE_DIR=$(mktemp -d "$HOME/.xiaomi-tv-tool.new.XXXXXX")
TEMP_DIR=$(mktemp -d)
trap 'rm -f "$TEMP_DIR/xiaomi-phone.zip" "$TEMP_DIR/xiaomi-phone.zip.sha256"; rmdir "$TEMP_DIR" 2>/dev/null || true; rm -rf "$STAGE_DIR"' EXIT HUP INT TERM
DOWNLOAD="https://github.com/$REPOSITORY/releases/latest/download"
echo "Dang tai bo cai Xiaomi TV tu github.com/$REPOSITORY (release latest)..."
curl -fL --retry 2 --connect-timeout 30 "$DOWNLOAD/xiaomi-phone.zip" -o "$TEMP_DIR/xiaomi-phone.zip"
curl -fsSL --retry 2 --connect-timeout 30 "$DOWNLOAD/xiaomi-phone.zip.sha256" -o "$TEMP_DIR/xiaomi-phone.zip.sha256"
echo "SHA-256 nha phat hanh cong bo: $(cut -d' ' -f1 "$TEMP_DIR/xiaomi-phone.zip.sha256")"
python3 - "$TEMP_DIR" "$STAGE_DIR" <<'PY'
import hashlib, json, pathlib, re, shutil, stat, sys, zipfile
temp, root = map(pathlib.Path, sys.argv[1:])
archive = temp / 'xiaomi-phone.zip'
expected = (temp / 'xiaomi-phone.zip.sha256').read_text().split()[0].lower()
if not re.fullmatch(r'[a-f0-9]{64}', expected):
    raise SystemExit('File SHA-256 khong hop le.')
h = hashlib.sha256()
with archive.open('rb') as f:
    for block in iter(lambda: f.read(1024*1024), b''):
        h.update(block)
if h.hexdigest() != expected:
    raise SystemExit('Bo cai tai chua day du hoac da thay doi; hay thu lai.')
root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive) as z:
    for entry in z.infolist():
        p = pathlib.PurePosixPath(entry.filename)
        if not p.parts or p.is_absolute() or '..' in p.parts or '\\' in entry.filename or ':' in entry.filename:
            raise SystemExit('Duong dan ZIP khong hop le.')
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise SystemExit('Khong cho phep lien ket trong ZIP.')
        destination = (root / entry.filename).resolve()
        try:
            destination.relative_to(root.resolve())
        except ValueError:
            raise SystemExit('Duong dan vuot thu muc cai dat.')
        if entry.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with z.open(entry) as src, destination.open('wb') as dst:
                shutil.copyfileobj(src, dst, 256*1024)
for folder in ('logs', 'profiles'):
    (root / folder).mkdir(exist_ok=True)
if not (root / 'manager.py').is_file():
    raise SystemExit('Bo cai thieu manager.py.')
compile((root / 'manager.py').read_text(encoding='utf-8-sig'), 'manager.py', 'exec')
for name, digest in json.loads((root / 'payload-hashes.json').read_text()).items():
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise SystemExit('Ten tai nguyen khong hop le.')
    f = root / name
    h = hashlib.sha256()
    with f.open('rb') as src:
        for block in iter(lambda: src.read(1024*1024), b''):
            h.update(block)
    if h.hexdigest() != digest:
        raise SystemExit('Tai nguyen khong khop SHA-256: ' + name)
print('Da san sang. Mo menu cai TV...')
PY
# Bản mới đã qua kiểm chứng ở trên; tới đây mới thay bản đang dùng.
if [ -d "$INSTALL_DIR" ]; then
  for d in logs profiles; do
    if [ -d "$INSTALL_DIR/$d" ]; then
      cp -r "$INSTALL_DIR/$d/." "$STAGE_DIR/$d/"
    fi
  done
  rm -rf "$BACKUP_DIR"
  mv "$INSTALL_DIR" "$BACKUP_DIR"
  echo "Da giu ban cai truoc o $BACKUP_DIR"
fi
if ! mv "$STAGE_DIR" "$INSTALL_DIR"; then
  if [ ! -e "$INSTALL_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    mv "$BACKUP_DIR" "$INSTALL_DIR"
  fi
  echo 'Khong kich hoat duoc ban moi; da thu tra lai ban cu.'
  exit 1
fi
python3 "$INSTALL_DIR/manager.py"
