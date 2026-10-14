# 📱 Руководство по сборке APK для Android (YaSave)

В данном руководстве описано 3 простых способа получить рабочий `.apk` файл для установки на Android-смартфон или планшет.

---

## 🚀 Способ 1: Автоматическая сборка через GitHub Actions (Самый простой, рекомендуется!)

Так как на Windows сборка Android APK через Buildozer требует компиляторов Linux и NDK, в проект уже добавлен настроенный CI/CD workflow: [`.github/workflows/build_apk.yml`](file:///.github/workflows/build_apk.yml).

### Шаги:
1. **Создайте репозиторий на GitHub** (публичный или приватный).
2. **Загрузите проект в репозиторий**:
   ```bash
   git init
   git add .
   git commit -m "Initial YaSave release"
   git branch -M main
   git remote add origin https://github.com/ВАШ_ЛОГИН/YaSave.git
   git push -u origin main
   ```
3. **Откройте вкладку "Actions"** в вашем репозитории на GitHub:
   - В списке слева выберите workflow **"Build Android APK"**.
   - Нажмите **"Run workflow"** (или сборка запустится автоматически при первом пуше).
4. **Скачайте готовый APK**:
   - Через ~6–8 минут сборка завершится зелёной галочкой ✅.
   - Внизу страницы запуска в блоке **Artifacts** появится архив **`YaSave-Debug-APK`**.
   - Скачайте его, распакуйте и установите полученный `.apk` на свой Android-телефон!

---

## 🐳 Способ 2: Сборка через Docker (Если у вас установлен Docker)

Если у вас установлен Docker Desktop на Windows:
```bash
docker run --rm -v "%cd%":/home/user/hostcwd kivy/buildozer android debug
```
Готовый `.apk` появится в папке `bin/`.

---

## 🐧 Способ 3: Сборка локально через WSL2 (Ubuntu на Windows)

Если у вас включен WSL (Windows Subsystem for Linux):

1. **Откройте Ubuntu в терминале** и перейдите в папку проекта:
   ```bash
   cd /mnt/c/Users/Van4ous/YaSave
   ```
2. **Установите системные зависимости**:
   ```bash
   sudo apt update
   sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
   pip3 install --user --upgrade buildozer cython virtualenv
   ```
3. **Запустите сборку**:
   ```bash
   buildozer -v android debug
   ```
4. После окончания процесса файл `YaSave-1.0.0-arm64-v8a_armeabi-v7a-debug.apk` будет лежать в папке `bin/`.

---

## 📲 Установка APK на телефон

1. Перенесите полученный `.apk` на Android через Telegram, USB-кабель или Google Drive.
2. В настройках телефона разрешите установку из неизвестных источников (если появится запрос).
3. При первом запуске YaSave запросит разрешение на запись в память для сохранения MP3 в папку `Download/YaSave`.
