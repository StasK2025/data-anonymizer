# Сборка дистрибутива (.exe) — этап 4 по ТЗ
# Результат: dist/TableAnonymizer.exe (one-file, без консоли, работает офлайн)
$ErrorActionPreference = "Stop"

python -m pip install pyinstaller

# ВАЖНО: Python 3.15 ставит abi3t-совместимость для ряда расширений (cryptography),
# которую PyInstaller не включает автоматически — добавляем вручную.
$pybase = python -c "import sys; print(sys.base_prefix)"
$abi3t = Join-Path $pybase "abi3t-compat\python3t.dll"
$extra = @()
if (Test-Path $abi3t) { $extra = @("--add-binary", "$abi3t;.") }

python -m PyInstaller --noconfirm --onefile --windowed `
    --name TableAnonymizer `
    --paths . `
    --collect-all cryptography `
    @extra `
    main.py

Write-Host "Готово: dist\TableAnonymizer.exe"
