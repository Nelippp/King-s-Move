#!/usr/bin/env bash
# Собирает игру и упаковывает ВСЁ (Qt-библиотеки + плагины) в ОДИН файл.
# Результат: dist/KingRoguelike  — один исполняемый self-extracting архив.
# На любом Debian x86_64:  ./KingRoguelike   (ничего ставить не нужно)
set -e
cd "$(dirname "$0")"

echo "[1/4] Сборка Release..."
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build build -j"$(nproc)" >/dev/null

APPDIR=$(mktemp -d /tmp/kinggame.XXXX)
trap 'rm -rf "$APPDIR"' EXIT
mkdir -p "$APPDIR/libs" "$APPDIR/plugins/platforms"
cp build/KingRoguelike "$APPDIR/game.bin"

echo "[2/4] Копируем Qt-библиотеки (рекурсивно по зависимости)..."
copy_deps() {  # $1 = binary/lib to scan, results go into APPDIR/libs
  ldd "$1" 2>/dev/null | awk '/=> \// {print $3}' | while read -r lib; do
    real=$(readlink -f "$lib")
    base=$(basename "$real")
    if [ ! -e "libs/$base" ]; then
      case "$real" in
        */libc.so*|*/libm.so*|*/libdl.so*|*/libpthread.so*|*/librt.so*|\
        */libgcc_s.so*|*/libstdc++.so*|*/ld-linux*|*/libresolv*|*/libnsl*|*/libcrypt*)
          ;; # системные glibc оставляем динамические — они есть на любом Debian
        *)
          cp -L "$real" "libs/" 2>/dev/null || true
          copy_deps "$real"
          ;;
      esac
    fi
  done
}
( cd "$APPDIR" && copy_deps game.bin )

echo "[3/4] Копируем Qt-плагины (платформа xcb/minimal/offscreen)..."
PLUG=$(qmake6 -query QT_INSTALL_PLUGINS)
for p in xcb minimal offscreen eglfs linuxfb; do
  [ -f "$PLUG/platforms/libq$p.so" ] && cp -L "$PLUG/platforms/libq$p.so" "$APPDIR/plugins/platforms/" || true
done
# зависимости самих плагинов
( cd "$APPDIR" && for pl in plugins/platforms/*.so; do copy_deps "$pl"; done ) 2>/dev/null || \
( cd "$APPDIR" && for pl in plugins/platforms/*.so; do
    ldd "$pl" | awk '/=> \// {print $3}' | while read -r lib; do
      real=$(readlink -f "$lib"); base=$(basename "$real")
      [ ! -e "libs/$base" ] && cp -L "$real" libs/ 2>/dev/null || true
    done
  done )

patchelf --set-rpath '$ORIGIN/libs' "$APPDIR/game.bin"
for pl in "$APPDIR"/plugins/platforms/*.so; do patchelf --set-rpath '$ORIGIN:$ORIGIN/../../libs' "$pl" 2>/dev/null || true; done

echo "[4/4] Упаковываем в ОДИН файл dist/KingRoguelike ..."
mkdir -p dist
cat > "$APPDIR/run.sh" <<'RUNEOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
export QT_QPA_PLATFORM_PLUGIN_PATH="$PWD/plugins/platforms"
exec "$PWD/game.bin" "$@"
RUNEOF
chmod +x "$APPDIR/run.sh"

makeself --gzip \
  "$APPDIR" "KingRoguelike" \
  "Рогалик: король против пешек на поле 12x12. Запуск: ./KingRoguelike" \
  ./run.sh
mv -f KingRoguelike dist/KingRoguelike 2>/dev/null || true
chmod +x dist/KingRoguelike
ls -lh dist/KingRoguelike
echo "Готово! Один файл: dist/KingRoguelike"
