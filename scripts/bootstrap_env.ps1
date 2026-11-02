param(
    [string]$ConfigPath = "$PSScriptRoot/../config/tools.json",
    [string]$EnvFile = "$PSScriptRoot/../.env",
    [string]$WorkspaceRoot = "",
    [switch]$SkipWinget,
    [switch]$SkipRepos,
    [switch]$SkipEnvs
)

$ErrorActionPreference = "Stop"

function Read-Config {
    param([string]$Path)
    return Get-Content -Raw -Encoding UTF8 $Path | ConvertFrom-Json
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Test-Binary {
    param([array]$Candidates, [string]$EnvVar)
    if ($EnvVar) {
        $envItem = Get-Item -Path "Env:$EnvVar" -ErrorAction SilentlyContinue
        if ($envItem -and (Test-Path -LiteralPath $envItem.Value)) {
            return $envItem.Value
        }
    }
    foreach ($candidate in $Candidates) {
        $expanded = [Environment]::ExpandEnvironmentVariables($candidate)
        if (Test-Path -LiteralPath $expanded) { return $expanded }
    }
    $leaf = [System.IO.Path]::GetFileName($Candidates[0])
    if ($leaf) {
        $cmd = Get-Command $leaf -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Install-WingetPackageIfMissing {
    param([string]$PackageId, [array]$Candidates, [string]$EnvVar)
    $existing = Test-Binary -Candidates $Candidates -EnvVar $EnvVar
    if ($existing) {
        Write-Host "[skip] $PackageId already present: $existing"
        return $existing
    }
    Write-Host "[install] winget $PackageId"
    winget install --id $PackageId --exact --accept-package-agreements --accept-source-agreements
    return (Test-Binary -Candidates $Candidates -EnvVar $EnvVar)
}

function Ensure-GitRepo {
    param(
        [string]$Name,
        [string]$RepoUrl,
        [string]$Checkout,
        [string]$ThirdPartyRoot
    )
    if (-not $RepoUrl) {
        Write-Host "[warn] $Name repo_url is empty; skip clone"
        return Join-Path $ThirdPartyRoot $Name
    }
    $target = Join-Path $ThirdPartyRoot $Name
    if (-not (Test-Path -LiteralPath $target)) {
        git clone $RepoUrl $target
    }
    Push-Location $target
    try {
        git fetch --all --tags
        git checkout $Checkout
    }
    finally {
        Pop-Location
    }
    return $target
}

function Ensure-MicromambaEnv {
    param(
        [string]$MicromambaBin,
        [string]$EnvName,
        [string]$PythonVersion,
        [string]$EnvRoot
    )
    Ensure-Directory -Path $EnvRoot
    & $MicromambaBin create -y -p (Join-Path $EnvRoot $EnvName) python=$PythonVersion pip | Out-Null
}

function Write-EnvLine {
    param(
        [System.Collections.Generic.List[string]]$Lines,
        [string]$Key,
        [string]$Value
    )
    $Lines.Add("$Key=$Value") | Out-Null
}

$config = Read-Config -Path $ConfigPath
if (-not $WorkspaceRoot) {
    $WorkspaceRoot = $config.paths.workspace_root
}

$thirdPartyRoot = $config.paths.third_party_root
$modelsRoot = $config.paths.models_root
$envsRoot = $config.paths.envs_root

Ensure-Directory -Path $WorkspaceRoot
Ensure-Directory -Path $thirdPartyRoot
Ensure-Directory -Path $modelsRoot
Ensure-Directory -Path $envsRoot

$resolved = @{}
foreach ($name in @("ffmpeg", "blender", "git", "micromamba")) {
    $tool = $config.tools.$name
    if ($SkipWinget) {
        $resolved[$name] = Test-Binary -Candidates $tool.binary_candidates -EnvVar $tool.env_var
    } else {
        $resolved[$name] = Install-WingetPackageIfMissing -PackageId $tool.installer.id -Candidates $tool.binary_candidates -EnvVar $tool.env_var
    }
}
$resolved["ffprobe"] = Test-Binary -Candidates $config.tools.ffprobe.binary_candidates -EnvVar $config.tools.ffprobe.env_var

if (-not $SkipRepos) {
    foreach ($name in @("cosyvoice", "whisperx", "hunyuan3d")) {
        $tool = $config.tools.$name
        $resolved["${name}_repo"] = Ensure-GitRepo -Name $name -RepoUrl $tool.repo_url -Checkout $tool.checkout -ThirdPartyRoot $thirdPartyRoot
    }
}

if (-not $SkipEnvs) {
    $micromamba = $resolved["micromamba"]
    if (-not $micromamba) {
        throw "micromamba not found; cannot create model environments"
    }
    foreach ($name in @("cosyvoice", "whisperx", "hunyuan3d")) {
        $tool = $config.tools.$name
        Ensure-MicromambaEnv -MicromambaBin $micromamba -EnvName $tool.env_name -PythonVersion "3.10" -EnvRoot $envsRoot
    }
}

$lines = [System.Collections.Generic.List[string]]::new()

function Resolve-OrEmpty {
    param([hashtable]$Map, [string]$Key)
    if ($Map.ContainsKey($Key) -and $Map[$Key]) {
        return $Map[$Key]
    }
    return ""
}

Write-EnvLine -Lines $lines -Key "AI_ANIME_FFMPEG_BIN" -Value (Resolve-OrEmpty -Map $resolved -Key "ffmpeg")
Write-EnvLine -Lines $lines -Key "AI_ANIME_FFPROBE_BIN" -Value (Resolve-OrEmpty -Map $resolved -Key "ffprobe")
Write-EnvLine -Lines $lines -Key "AI_ANIME_BLENDER_BIN" -Value (Resolve-OrEmpty -Map $resolved -Key "blender")
Write-EnvLine -Lines $lines -Key "AI_ANIME_THIRD_PARTY_ROOT" -Value $thirdPartyRoot
Write-EnvLine -Lines $lines -Key "AI_ANIME_MODELS_ROOT" -Value $modelsRoot
Write-EnvLine -Lines $lines -Key "AI_ANIME_ENVS_ROOT" -Value $envsRoot

foreach ($name in @("cosyvoice", "whisperx", "hunyuan3d")) {
    $tool = $config.tools.$name
    $repoRoot = Join-Path $thirdPartyRoot $name
    $template = $tool.cmd_template.Replace("{repo_root}", $repoRoot)
    Write-EnvLine -Lines $lines -Key $tool.env_var -Value $template
}

Set-Content -LiteralPath $EnvFile -Value ($lines -join [Environment]::NewLine) -Encoding UTF8
Write-Host "[done] wrote environment file: $EnvFile"
Write-Host "[next] review repo_url placeholders in config/tools.json and install tool-specific Python dependencies inside each micromamba env"
