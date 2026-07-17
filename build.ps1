param(
    [string]$Target = "doxygon"
)

$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

$DIST = "dist"
$BUILD = "build"
$VERSION_FILE = "version_info.txt"

Write-Host "Reading version from pyproject.toml..."
Write-Host ""

$Version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
    throw "Failed to read version from pyproject.toml."
}

$Version = $Version.Trim()

if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "Version must be MAJOR.MINOR.PATCH (e.g. 1.0.1)"
}

$Major = [int]$Matches[1]
$Minor = [int]$Matches[2]
$Patch = [int]$Matches[3]
$BuildNo = 0

Write-Host "Doxygon version: $Version"
Write-Host ""

@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($Major,$Minor,$Patch,$BuildNo),
    prodvers=($Major,$Minor,$Patch,$BuildNo),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0,0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'041104B0',
        [
          StringStruct(u'CompanyName',u'Goxydon Project'),
          StringStruct(u'FileDescription',u'Doxygon'),
          StringStruct(u'FileVersion',u'$Version'),
          StringStruct(u'InternalName',u'$Target'),
          StringStruct(u'OriginalFilename',u'$Target.exe'),
          StringStruct(u'ProductName',u'Doxygon'),
          StringStruct(u'ProductVersion',u'$Version')
        ]
      )
    ]),
    VarFileInfo([
      VarStruct(u'Translation',[1041,1200])
    ])
  ]
)
"@ | Set-Content $VERSION_FILE -Encoding UTF8

Write-Host "Cleaning up build artifacts..."
Write-Host ""

Remove-Item -Recurse -Force $DIST -ErrorAction Ignore
Remove-Item -Recurse -Force $BUILD -ErrorAction Ignore
Remove-Item -Force *.spec -ErrorAction Ignore

Write-Host "Starting build process..."
Write-Host ""

try {
    pyinstaller `
        run_doxygon.py `
        --name $Target `
        --onefile `
        --clean `
        --noconfirm `
        --log-level INFO `
        --collect-submodules doxygon `
        --version-file $VERSION_FILE

    if ($LASTEXITCODE -ne 0) {
	throw "Build failed."
    }
    Copy-Item `
        -Path ".\dist\$Target.exe" `
        -Destination ".\$Target.exe" `
        -Force

    Write-Host "Created : $Target.exe"
    Write-Host "Version : $Version"
}
finally {
    Remove-Item $VERSION_FILE -ErrorAction Ignore
}

Get-Item .\$Target.exe | Select Name, Length, LastWriteTime

