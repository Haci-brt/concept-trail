# Concept Trail - Windows'a tek komutla kurulum:
#
#   irm https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.ps1 | iex
#
# Uygulamayı %LOCALAPPDATA%\Programs\ConceptTrail içine indirir, kendi Python
# ortamını kurar, masaüstüne ve Başlat menüsüne logolu bir kısayol koyar ve
# uygulamayı açar. Notlar Belgeler\Concept Trail klasöründe durur; güncelleme
# (aynı komutu yeniden çalıştırmak) onlara dokunmaz. Yönetici izni gerekmez.
#
# Ayarlanabilir (ortam değişkeni): CT_APP_DIR, CT_VAULT, CT_SOURCE (zip yolu
# ya da adresi), CT_NO_LAUNCH=1, CT_NO_SHORTCUT=1.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"      # indirme ilerleme çubuğu Invoke-WebRequest'i çok yavaşlatır

$Repo = "Haci-brt/concept-trail"
$Branch = "main"
$AppDir = if ($env:CT_APP_DIR) { $env:CT_APP_DIR } else { Join-Path $env:LOCALAPPDATA "Programs\ConceptTrail" }
$Vault = if ($env:CT_VAULT) { $env:CT_VAULT } else { Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Concept Trail" }
$Source = if ($env:CT_SOURCE) { $env:CT_SOURCE } else { "https://github.com/$Repo/archive/refs/heads/$Branch.zip" }

function Step([string]$text) { Write-Host "> $text" -ForegroundColor Cyan }
function Done([string]$text) { Write-Host "+ $text" -ForegroundColor Green }

function Find-Python {
    # "python" may be the Microsoft Store placeholder, which prints a hint and
    # exits with an error: only a real 3.10+ interpreter counts
    $candidates = @(@("py", "-3"), @("python"), @("python3"))
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $rest = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $found = & $exe @rest -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -Last 1).Trim() }
        } catch { }
    }
    foreach ($version in "313", "312", "311") {
        $path = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"
        if (Test-Path $path) { return $path }
    }
    return $null
}

Write-Host ""
Write-Host "  Concept Trail kuruluyor" -ForegroundColor White
Write-Host "  Uygulama: $AppDir"
Write-Host "  Notlar:   $Vault"
Write-Host ""

# 1. Python
Step "Python aranıyor"
$Python = Find-Python
if (-not $Python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "Python 3.10 ya da üstü bulunamadı. winget ile Python 3.12 (yalnız bu kullanıcıya) kurulsun mu? [E/h]"
        if ($answer -match '^(h|n)') { throw "Python gerekli: https://www.python.org/downloads/ adresinden kurup komutu yeniden çalıştır." }
        Step "Python 3.12 kuruluyor (winget)"
        winget install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
        $Python = Find-Python
    }
    if (-not $Python) { throw "Python 3.10+ bulunamadı. https://www.python.org/downloads/ adresinden kurup komutu yeniden çalıştır." }
}
Done "Python: $Python"

# 2. The app itself
Step "Uygulama indiriliyor"
$Temp = Join-Path ([IO.Path]::GetTempPath()) ("concept-trail-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Temp | Out-Null
try {
    $Zip = Join-Path $Temp "app.zip"
    if (Test-Path $Source) { Copy-Item $Source $Zip } else { Invoke-WebRequest -UseBasicParsing -Uri $Source -OutFile $Zip }
    Expand-Archive -Path $Zip -DestinationPath (Join-Path $Temp "x") -Force
    $Extracted = Get-ChildItem (Join-Path $Temp "x") | Select-Object -First 1
    if (-not (Test-Path (Join-Path $Extracted.FullName "main.py"))) { throw "İndirilen arşivde main.py yok: $Source" }

    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    # an update replaces the code, never the environment or notes kept beside it
    Get-ChildItem -Force $AppDir | Where-Object { $_.Name -notin ".venv", "notes" } | Remove-Item -Recurse -Force
    Copy-Item -Path (Join-Path $Extracted.FullName "*") -Destination $AppDir -Recurse -Force
} finally {
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
}
Done "Uygulama indirildi"

# 3. Its own Python environment
$Venv = Join-Path $AppDir ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Step "Python ortamı oluşturuluyor"
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Python ortamı oluşturulamadı." }
}
Step "Bağımlılıklar kuruluyor (ilk kurulumda birkaç dakika sürebilir; PyQt6 WebEngine büyük)"
& $VenvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $AppDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Bağımlılıklar kurulamadı; yukarıdaki pip hatasına bak." }
Done "Bağımlılıklar kuruldu"

# 4. Notes folder and launchers
New-Item -ItemType Directory -Force -Path $Vault | Out-Null
if (-not $env:CT_NO_SHORTCUT) {
    Step "Masaüstü ve Başlat menüsü kısayolu oluşturuluyor"
    & $VenvPython (Join-Path $AppDir "scripts\make_shortcut.py") --vault $Vault
    if ($LASTEXITCODE -ne 0) { throw "Kısayol oluşturulamadı." }
}

Write-Host ""
Done "Concept Trail kuruldu."
Write-Host "  Açmak için masaüstündeki Concept Trail simgesine çift tıkla."
Write-Host "  Güncellemek için aynı komutu yeniden çalıştır; notların korunur."
Write-Host "  Kaldırmak için: $AppDir klasörünü ve kısayolları sil (notlar $Vault içinde kalır)."
Write-Host ""

# 5. Open it
if (-not $env:CT_NO_LAUNCH) {
    Start-Process -FilePath (Join-Path $Venv "Scripts\pythonw.exe") -WorkingDirectory $AppDir `
        -ArgumentList @("`"$(Join-Path $AppDir 'main.py')`"", "--vault", "`"$Vault`"")
}
