# Default is local preflight ONLY. Never reads .env, P2 history, or an ambient key.
[CmdletBinding()]
param(
    [switch]$AuthorizePaidExperiment,
    [switch]$ConfirmNewAccountKey,
    [ValidatePattern('^[A-Za-z0-9]{1,40}$')][string]$RunId = 'be20261022once'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Existing Python venv is required.' }
Push-Location $repo
try {
    & $python -m scripts.deepseek_be
    if ($LASTEXITCODE -ne 0) { throw 'Dry run failed; no paid request.' }
    if ($AuthorizePaidExperiment) {
        & $python -m scripts.preflight_deepseek_be --require-clean
    } else {
        & $python -m scripts.preflight_deepseek_be
    }
    if ($LASTEXITCODE -ne 0) { throw 'Local preflight blocked; no paid request.' }
    if (!$AuthorizePaidExperiment) {
        Write-Output 'PREFLIGHT ONLY. Paid execution is not authorized or started.'
        return
    }
    if (!$ConfirmNewAccountKey) { throw 'Fresh own-account key confirmation required; no paid request.' }
    $destination = Join-Path $repo ('data\quality-20261022\deepseek-be-paid-' + $RunId)
    if (Test-Path -LiteralPath $destination) { throw 'Run ID exists. Do not retry or overwrite evidence.' }
    # The operator personally supplies a NEW own-account key after separate approval.
    # Never fall back to an existing environment variable or inherited historical key.
    $secure = Read-Host 'Enter a NEW own-account DeepSeek key (not any historical/inherited key)' -AsSecureString
    try {
        if ($secure.Length -eq 0) { throw 'Empty key; no paid request.' }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $python
        $psi.WorkingDirectory = $repo
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.Arguments = '-m scripts.deepseek_be --execute-paid --acknowledge-public-data --price-date 2026-10-22 --budget-usd 0.04 --run-id ' + $RunId
        $psi.EnvironmentVariables['RESEARCH_OPENAI_API_KEY'] = [Net.NetworkCredential]::new('', $secure).Password
        foreach ($name in @('LANGSMITH_TRACING','LANGSMITH_TRACING_V2','LANGCHAIN_TRACING','LANGCHAIN_TRACING_V2','LANGSMITH_OTEL_ENABLED','DD_TRACE_ENABLED')) {
            $psi.EnvironmentVariables[$name] = 'false'
        }
        $psi.EnvironmentVariables['OTEL_SDK_DISABLED'] = 'true'
        $psi.EnvironmentVariables['HF_HUB_OFFLINE'] = '1'
        $psi.EnvironmentVariables['TRANSFORMERS_OFFLINE'] = '1'
        $psi.EnvironmentVariables['PYTHONUTF8'] = '1'
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $psi
        $null = $process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        # Do not echo arbitrary child errors/bodies. Evidence/summary stays in the new directory.
        $null = $stdoutTask.GetAwaiter().GetResult()
        $null = $stderrTask.GetAwaiter().GetResult()
        $result = $process.ExitCode
        Write-Output ('Experiment exit code: ' + $result + '; evidence directory: ' + $destination)
        if ($result -ne 0) { throw 'Experiment stopped. Review preserved evidence; do not automatically retry.' }
    } finally {
        if ($psi) { $psi.EnvironmentVariables.Remove('RESEARCH_OPENAI_API_KEY') }
        $secure.Dispose()
        if ($process) { $process.Dispose() }
    }
} finally {
    Pop-Location
}
