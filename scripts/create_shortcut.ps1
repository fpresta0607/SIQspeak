param(
    [string]$SiqDir
)

try {
    $ws = New-Object -ComObject WScript.Shell
    $desktop = $ws.SpecialFolders('Desktop')
    $sc = $ws.CreateShortcut([IO.Path]::Combine($desktop, 'SIQspeak.lnk'))
    $sc.TargetPath = Join-Path $SiqDir '.venv\Scripts\pythonw.exe'
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
}
