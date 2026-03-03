# Create SIQspeak desktop shortcut
# Usage: powershell -File create_shortcut.ps1

# Determine SIQspeak directory (parent of scripts folder)
$SiqDir = Split-Path -Parent $PSScriptRoot

$pythonw = Join-Path $SiqDir '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host '   [!] pythonw.exe not found. Shortcut skipped.'
    exit 1
}

try {
    $ws = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnkPath = Join-Path $desktop 'SIQspeak.lnk'
    $sc = $ws.CreateShortcut($lnkPath)
    $sc.TargetPath = $pythonw
    $sc.Arguments = '-m siqspeak'
    $sc.WorkingDirectory = $SiqDir
    $icoPath = Join-Path $SiqDir 'dictate.ico'
    if (Test-Path $icoPath) {
        $sc.IconLocation = "$icoPath,0"
    }
    $sc.Description = 'SIQspeak - local speech-to-text'
    $sc.Save()
    Write-Host '   [OK] Desktop shortcut created.'
} catch {
    Write-Host "   [!] Shortcut failed: $($_.Exception.Message)"
    exit 1
}
