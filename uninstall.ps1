# Concept Trail - Windows'tan kaldırma:
#
#   irm https://raw.githubusercontent.com/Haci-brt/concept-trail/main/uninstall.ps1 | iex
#
# ya da kurulu kopyasıyla:
#
#   powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\ConceptTrail\uninstall.ps1"
#
# Uygulama klasörünü ve install.ps1'in koyduğu masaüstü ve Başlat menüsü
# kısayollarını kaldırır. Ayar klasörünü (%APPDATA%\ConceptTrail: model
# sağlayıcıları, API anahtarları, tercihler) silmeden önce sorar. Notlara
# dokunmaz; notlar uygulama klasörünün içindeyse onları silmek için ayrıca,
# açıkça onay ister.
#
# Ayarlanabilir (ortam değişkeni): CT_APP_DIR (kurulumda verdiysen aynısı),
# CT_PORT (açık uygulamanın arandığı port, varsayılan 8765), CT_NO_PROMPT=1
# (hiçbir şey sorma, her soruya "hayır": ayarlar ve notlar kalır).

$ErrorActionPreference = "Stop"

$Marker = ".concept-trail-app"
$Port = if ($env:CT_PORT) { [int]$env:CT_PORT } else { 8765 }
$AppDir = if ($env:CT_APP_DIR) { $env:CT_APP_DIR } else { Join-Path $env:LOCALAPPDATA "Programs\ConceptTrail" }
$AppDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($AppDir).TrimEnd('\')
# where the app keeps its settings (server/providers.py: config_dir)
$ConfigBase = if ($env:FIKIR_CONFIG_DIR) { $env:FIKIR_CONFIG_DIR } else { $env:APPDATA }
$ConfigDirs = @("ConceptTrail", "FikirNotDefteri") | ForEach-Object { Join-Path $ConfigBase $_ } |
    Where-Object { Test-Path -LiteralPath $_ }
$DefaultVault = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Concept Trail"

function Step([string]$text) { Write-Host "> $text" -ForegroundColor Cyan }
function Done([string]$text) { Write-Host "+ $text" -ForegroundColor Green }

# Without a console to ask (a pipe, CI, -NonInteractive) or with
# CT_NO_PROMPT=1 every answer is no.
function Read-Answer([string]$question) {
    if ($env:CT_NO_PROMPT) { Write-Host "$question : (CT_NO_PROMPT)"; return "" }
    try { return "$(Read-Host $question)".Trim() } catch { return "" }
}

# y/N: only a clear yes removes anything
function Ask([string]$question) {
    return (Read-Answer "$question [e/H]") -match '^(e|evet|y|yes)$'
}

function Test-OurInstall([string]$dir) {
    if (Test-Path -LiteralPath (Join-Path $dir $Marker)) { return $true }
    return (Test-Path -LiteralPath (Join-Path $dir "main.py") -PathType Leaf) -and
           (Test-Path -LiteralPath (Join-Path $dir "server") -PathType Container)
}

# the same check as install.ps1: a running copy holds its DLLs open
function Test-Running([string]$dir) {
    $main = Join-Path $dir "main.py"
    try {
        $mine = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith("$dir\", [StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($main, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
        if ($mine.Count -gt 0) { return $true }
    } catch { }
    try {
        $state = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/state" -TimeoutSec 3
        if ($state.app -eq "concept-trail") { return $true }
    } catch { }
    return $false
}

# Only the shortcuts that open this install (scripts/make_shortcut.py sets
# the working folder and main.py's path); a checkout's own shortcut stays.
function Remove-Shortcuts([string]$dir) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($where in "Desktop", "Programs") {
        $folder = [Environment]::GetFolderPath($where)
        if (-not $folder) { continue }
        $path = Join-Path $folder "Concept Trail.lnk"
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $link = $shell.CreateShortcut($path)
        $here = ("$($link.WorkingDirectory)".TrimEnd('\') -ieq $dir) -or
                ("$($link.Arguments)".IndexOf((Join-Path $dir "main.py"), [StringComparison]::OrdinalIgnoreCase) -ge 0)
        if ($here) {
            Remove-Item -LiteralPath $path -Force
            Done "Kısayol kaldırıldı: $path"
        } else {
            Write-Host "  Başka bir klasörü açan kısayol bırakıldı: $path"
        }
    }
}

Write-Host ""
Write-Host "  Concept Trail kaldırılıyor" -ForegroundColor White
Write-Host "  Uygulama: $AppDir"
Write-Host ""

$RemoveApp = $false
if (-not (Test-Path -LiteralPath $AppDir)) {
    Write-Host "  Uygulama klasörü yok (zaten kaldırılmış olabilir); kısayollara ve ayarlara bakılıyor."
} elseif (-not (Test-OurInstall $AppDir)) {
    throw ("$AppDir bir Concept Trail kurulumuna benzemiyor; hiçbir şey silinmedi. " +
           "Kurulumda CT_APP_DIR verdiysen kaldırırken de aynısını ver.")
} elseif (Test-Running $AppDir) {
    throw "Concept Trail şu an açık. Önce uygulamayı kapat (açık pencereyi ve varsa sunucuyu), sonra yeniden çalıştır."
} else {
    $RemoveApp = $true
}

# Notes kept inside the app folder (main.py's default ./notes) are the
# writer's work: removed only when asked for by name, never by a plain yes.
$Notes = Join-Path $AppDir "notes"
$KeepNotes = $true
if ($RemoveApp -and @(Get-ChildItem -Force -LiteralPath $Notes -ErrorAction SilentlyContinue).Count -gt 0) {
    Write-Host "  Uygulama klasörünün içinde notlar var: $Notes" -ForegroundColor Yellow
    $answer = Read-Answer "  Bu notlar da KALICI olarak silinsin mi? Silmek için 'sil' yaz, korumak için Enter'a bas"
    $KeepNotes = $answer -ne "sil"
}

if ($RemoveApp) {
    Step "Uygulama klasörü kaldırılıyor"
    # a shell standing inside the folder would keep it from being removed
    if ((Get-Location).Path.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase)) { Set-Location -LiteralPath $HOME }
    Get-ChildItem -Force -LiteralPath $AppDir |
        Where-Object { -not ($KeepNotes -and $_.Name -eq "notes") } |
        Remove-Item -Recurse -Force
    if (@(Get-ChildItem -Force -LiteralPath $AppDir).Count -eq 0) {
        Remove-Item -LiteralPath $AppDir -Force
        Done "Uygulama kaldırıldı"
    } else {
        Done "Uygulama kaldırıldı; notlar yerinde bırakıldı: $Notes"
    }
}

Step "Kısayollar"
Remove-Shortcuts $AppDir

if ($ConfigDirs) {
    Write-Host ""
    Write-Host "  Ayarlar: $($ConfigDirs -join ', ')"
    Write-Host "  (model sağlayıcıları, API anahtarları, araştırma token'ı, tercihler, günlük)"
    if (Ask "  Ayarlar da silinsin mi?") {
        foreach ($dir in $ConfigDirs) { Remove-Item -LiteralPath $dir -Recurse -Force }
        Done "Ayarlar silindi"
    } else {
        Write-Host "  Ayarlar yerinde bırakıldı; yeniden kurarsan kaldığın yerden devam eder."
    }
}

Write-Host ""
Done "Concept Trail kaldırıldı."
Write-Host "  Notlarına dokunulmadı (kurulumun varsayılan yeri: $DefaultVault)."
Write-Host ""
