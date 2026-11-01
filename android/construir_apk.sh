#!/usr/bin/env bash
# Construye LaZoo.apk sin Gradle: aapt2 + javac + d8 + zipalign + apksigner.
# Necesita JDK 17 y Android SDK (platforms;android-34, build-tools;34.0.0).
#   ANDROID_SDK=~/android-sdk JAVA_HOME=~/jdk17 ./construir_apk.sh [salida.apk]
set -euo pipefail
cd "$(dirname "$0")"
SDK="${ANDROID_SDK:-${ANDROID_HOME:-$HOME/android-sdk}}"
BT="$SDK/build-tools/34.0.0"
JAR="$SDK/platforms/android-34/android.jar"
[ -n "${JAVA_HOME:-}" ] && export PATH="$JAVA_HOME/bin:$PATH"
OUT="${1:-build/LaZoo.apk}"
rm -rf build && mkdir -p build/res build/gen build/classes build/dex
"$BT/aapt2" compile --dir res -o build/res/res.zip
"$BT/aapt2" link -o build/base.apk -I "$JAR" --manifest AndroidManifest.xml -A assets \
  --java build/gen build/res/res.zip
javac --release 11 -nowarn -classpath "$JAR" -d build/classes $(find src build/gen -name '*.java')
"$BT/d8" --release --min-api 24 --lib "$JAR" --output build/dex $(find build/classes -name '*.class')
cp build/base.apk build/unsigned.apk
python3 -c "import zipfile; zipfile.ZipFile('build/unsigned.apk','a').write('build/dex/classes.dex','classes.dex')"
"$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk
# Clave propia de pruebas (no de Google Play). Se crea una vez y se reutiliza.
KS="${LAZOO_KEYSTORE:-$HOME/.lazoo/lazoo-pruebas.jks}"
if [ ! -f "$KS" ]; then
  mkdir -p "$(dirname "$KS")"
  keytool -genkeypair -keystore "$KS" -storepass lazoopruebas -keypass lazoopruebas -alias lazoo \
    -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=GUERRILLA, O=LaZoo" >/dev/null
fi
mkdir -p "$(dirname "$OUT")"
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:lazoopruebas --ks-key-alias lazoo --out "$OUT" build/aligned.apk
"$BT/apksigner" verify --print-certs "$OUT" | head -3
echo "Listo: $OUT"
