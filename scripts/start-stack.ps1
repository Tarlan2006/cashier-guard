#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Check,
    [ValidateRange(10, 600)][int]$StartupTimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stackDir = Join-Path $root 'work/stack'
$statePath = Join-Path $stackDir 'windows-state.json'
if ($env:OS -ne 'Windows_NT') { throw 'This launcher requires Windows. Use scripts/start-stack.sh on Linux/macOS.' }
if ($Stop -and $Check) { throw 'Use either -Stop or -Check.' }

function Read-StackState {
    if (Test-Path -LiteralPath $statePath) {
        return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    return $null
}

if ($Stop) {
    $state = Read-StackState
    if ($null -eq $state) { Write-Host 'No stack started by this script is registered.'; return }
    $owner = Get-Process -Id $state.owner_pid -ErrorAction SilentlyContinue
    if ($null -eq $owner -or $owner.StartTime.ToUniversalTime().Ticks.ToString() -ne $state.owner_started) {
        Write-Host 'Stale stack record; no process was stopped.'
        return
    }
    try { $stopEvent = [Threading.EventWaitHandle]::OpenExisting($state.stop_event) }
    catch { throw 'The owning launcher is not accepting stop requests. No unrelated process was stopped.' }
    try { [void]$stopEvent.Set() } finally { $stopEvent.Dispose() }
    $until = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $until) {
        if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'Stack stopped.'; return }
        $current = Read-StackState
        if ($null -eq $current -or $current.stop_event -ne $state.stop_event) { return }
        Start-Sleep -Milliseconds 200
    }
    throw 'Stop was requested, but cleanup is still pending. Check the owning PowerShell window.'
}

function Require-Command([string]$Name, [string]$Install) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "Missing $Name. Prepare it explicitly: $Install" }
    return $command.Source
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments, [string]$Directory, [string]$Remedy) {
    Push-Location $Directory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Preparation/check failed (exit $LASTEXITCODE). $Remedy" }
    } finally { Pop-Location }
}

function Protect-SecretFile([string]$Path) {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = Get-Acl -LiteralPath $Path
    $entries = @($acl.Access)
    if ($acl.AreAccessRulesProtected -and $entries.Count -eq 1 -and
        $entries[0].IdentityReference.Translate([Security.Principal.SecurityIdentifier]) -eq $sid -and
        $entries[0].FileSystemRights -eq [Security.AccessControl.FileSystemRights]::FullControl -and
        $entries[0].AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow) { return }
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($entry in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($entry) }
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

# A Windows Job Object owns all three process trees, including Python's venv
# redirector, the resident model worker and FFmpeg. Create suspended, assign,
# then resume: no descendant can escape during process startup. Closing the
# job (also when PowerShell exits) kills only its members. Never kill by port.
if (-not ('CashierGuard.WindowsStackJob' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
namespace CashierGuard {
    public sealed class WindowsStackJob : IDisposable {
        [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS {
            public ulong a, b, c, d, e, f;
        }
        [StructLayout(LayoutKind.Sequential)] struct BASIC_LIMITS {
            public long processTime, jobTime;
            public uint flags;
            public UIntPtr minWorkingSet, maxWorkingSet;
            public uint activeProcesses;
            public UIntPtr affinity;
            public uint priority, scheduling;
        }
        [StructLayout(LayoutKind.Sequential)] struct EXTENDED_LIMITS {
            public BASIC_LIMITS basic;
            public IO_COUNTERS io;
            public UIntPtr processMemory, jobMemory, peakProcessMemory, peakJobMemory;
        }
        [StructLayout(LayoutKind.Sequential)] struct SECURITY_ATTRIBUTES {
            public int length;
            public IntPtr descriptor;
            public int inherit;
        }
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct STARTUPINFO {
            public int cb;
            public string reserved, desktop, title;
            public uint x, y, xSize, ySize, xCount, yCount, fill, flags;
            public ushort show, reservedSize;
            public IntPtr reservedPointer, stdin, stdout, stderr;
        }
        [StructLayout(LayoutKind.Sequential)] struct PROCESS_INFORMATION {
            public IntPtr process, thread;
            public uint pid, tid;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool SetInformationJobObject(IntPtr job, int kind, ref EXTENDED_LIMITS info, uint length);
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern IntPtr CreateFile(string path, uint access, uint share, ref SECURITY_ATTRIBUTES security,
                                      uint creation, uint attributes, IntPtr template);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern bool CreateProcess(string app, StringBuilder command, IntPtr processSecurity,
            IntPtr threadSecurity, bool inherit, uint flags, IntPtr env, string cwd,
            ref STARTUPINFO startup, out PROCESS_INFORMATION process);
        [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr process, uint code);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        IntPtr job;
        public WindowsStackJob() {
            job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new Win32Exception();
            var limits = new EXTENDED_LIMITS();
            limits.basic.flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits))) {
                int error = Marshal.GetLastWin32Error(); Dispose(); throw new Win32Exception(error);
            }
        }
        public int Start(string executable, string command, string cwd, string outFile, string errFile) {
            var security = new SECURITY_ATTRIBUTES();
            security.length = Marshal.SizeOf(security); security.inherit = 1;
            IntPtr input = IntPtr.Zero, output = IntPtr.Zero, error = IntPtr.Zero;
            var pi = new PROCESS_INFORMATION();
            try {
                input = CreateFile("NUL", 0x80000000, 3, ref security, 3, 0x80, IntPtr.Zero);
                output = CreateFile(outFile, 0x40000000, 3, ref security, 2, 0x80, IntPtr.Zero);
                error = CreateFile(errFile, 0x40000000, 3, ref security, 2, 0x80, IntPtr.Zero);
                if (input == new IntPtr(-1) || output == new IntPtr(-1) || error == new IntPtr(-1))
                    throw new Win32Exception();
                var si = new STARTUPINFO(); si.cb = Marshal.SizeOf(si);
                si.flags = 0x100; si.stdin = input; si.stdout = output; si.stderr = error;
                if (!CreateProcess(executable, new StringBuilder(command), IntPtr.Zero, IntPtr.Zero,
                    true, 0x08000004, IntPtr.Zero, cwd, ref si, out pi)) throw new Win32Exception();
                if (!AssignProcessToJobObject(job, pi.process)) throw new Win32Exception();
                if (ResumeThread(pi.thread) == uint.MaxValue) throw new Win32Exception();
                return (int)pi.pid;
            } catch {
                if (pi.process != IntPtr.Zero) TerminateProcess(pi.process, 1);
                throw;
            } finally {
                foreach (var handle in new[] { input, output, error, pi.thread, pi.process })
                    if (handle != IntPtr.Zero && handle != new IntPtr(-1)) CloseHandle(handle);
            }
        }
        public void Dispose() { if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; } }
    }
}
'@
}

function Quote-NativeArgument([string]$Value) {
    # Windows CommandLineToArgvW / C runtime quoting, including paths with spaces.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

$lock = $null
$stopEvent = $null
$job = $null
$ownsState = $false
$savedEnvironment = @{}
try {
    [void](New-Item -ItemType Directory -Path $stackDir -Force)
    try { $lock = [IO.File]::Open((Join-Path $stackDir 'windows.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Another Windows stack launcher owns this checkout. Use scripts/start-stack.ps1 -Stop.' }

    $mlPython = Join-Path $root 'ml2/.venv/Scripts/python.exe'
    $backendPython = Join-Path $root 'backend/.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $mlPython)) {
        throw 'Missing ML venv. Run: py -3.12 -m venv ml2/.venv; ml2/.venv/Scripts/python.exe -m pip install -r ml2/requirements.txt'
    }
    Invoke-Checked $mlPython @('-c', 'import sys; from importlib.metadata import version; from packaging.requirements import Requirement; assert sys.version_info[:2] == (3,12); requirements=[Requirement(line.strip()) for line in open(sys.argv[1]) if line.strip() and not line.lstrip().startswith(chr(35))]; assert all(version(r.name) in r.specifier for r in requirements)', (Join-Path $root 'ml2/requirements.txt')) $root 'Use Python 3.12 and pip install -r ml2/requirements.txt.'
    $uv = Require-Command 'uv.exe' 'winget install --id astral-sh.uv -e (then reopen PowerShell)'
    $node = Require-Command 'node.exe' 'winget install --id OpenJS.NodeJS.LTS -e'
    $npm = Require-Command 'npm.cmd' 'Install Node.js 22.12+ or 24, then reopen PowerShell.'
    $nodeVersion = (& $node -p 'process.versions.node').Trim()
    $version = [version]$nodeVersion
    if (-not (($version.Major -eq 22 -and $version.Minor -ge 12) -or $version.Major -eq 24)) {
        throw "Unsupported Node $nodeVersion. Install Node.js 22.12+ (22.x) or 24.x."
    }
    foreach ($binary in @('ffmpeg.exe', 'ffprobe.exe')) {
        [void](Require-Command $binary 'winget install --id Gyan.FFmpeg -e; add its bin directory to PATH and reopen PowerShell.')
    }
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw 'Missing backend Python 3.14 venv. Run: uv python install 3.14; cd backend; uv venv --python 3.14; uv sync --frozen'
    }
    Invoke-Checked $backendPython @('-c', 'import sys; assert sys.version_info[:2] == (3,14)') $root 'Recreate backend/.venv explicitly with uv venv --python 3.14.'
    foreach ($port in @(8000, 8001, 8002)) {
        $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $port)
        try { $listener.Start() } catch { throw "Port $port is occupied. No existing process was stopped." }
        finally { $listener.Stop() }
    }

    Write-Host 'Checking backend lockfile: uv sync --frozen (may install locked dependencies; no lockfile changes).'
    Invoke-Checked $uv @('sync', '--frozen') (Join-Path $root 'backend') 'Run uv sync --frozen in backend; see the error above.'
    if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/dist/index.html'))) {
        Write-Host 'Frontend build missing: running npm ci and npm run build (explicit preparation; registry access required).'
        Invoke-Checked $npm @('ci') (Join-Path $root 'frontend') 'Run npm ci in frontend; no package/lockfile edits are made by this launcher.'
        Invoke-Checked $npm @('run', 'build') (Join-Path $root 'frontend') 'Run npm run build in frontend; see the build error above.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/dist/index.html'))) { throw 'Frontend build did not create frontend/dist/index.html.' }

    # Parse .env with backend's existing dependency; values travel only in memory.
    $envPath = Join-Path $root '.env'
    $values = @{}
    if (Test-Path -LiteralPath $envPath) {
        $json = & $backendPython -c 'import json,sys; from dotenv import dotenv_values; print(json.dumps(dotenv_values(sys.argv[1])))' $envPath
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read root .env.' }
        ($json | ConvertFrom-Json).PSObject.Properties | ForEach-Object { if ($null -ne $_.Value) { $values[$_.Name] = [string]$_.Value } }
    }
    if (-not $values.ContainsKey('API_KEY') -or [string]::IsNullOrWhiteSpace($values['API_KEY']) -or $values['API_KEY'] -eq 'replace-with-your-own-key') {
        # Create/protect before writing secret bytes. Never print the value.
        if (-not (Test-Path -LiteralPath $envPath)) { [IO.File]::WriteAllText($envPath, '') }
        Protect-SecretFile $envPath
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $values['API_KEY'] = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
        $content = [IO.File]::ReadAllText($envPath)
        $content = [regex]::Replace($content, '(?m)^\s*(?:export\s+)?API_KEY\s*=.*(?:\r?\n|$)', '')
        [IO.File]::WriteAllText($envPath, $content.TrimEnd() + "`r`nAPI_KEY=" + $values['API_KEY'] + "`r`n", (New-Object Text.UTF8Encoding($false)))
        Write-Host 'Generated private API_KEY in ignored .env (value hidden).'
    } else { Protect-SecretFile $envPath }

    foreach ($name in $values.Keys) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        # An explicit shell setting wins, except the key stored for the website.
        if ($name -eq 'API_KEY' -or $null -eq [Environment]::GetEnvironmentVariable($name, 'Process')) {
            [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
        }
    }
    $models = $env:ML_MODELS_DIR
    if ([string]::IsNullOrWhiteSpace($models)) { $models = Join-Path $root 'ml2/models' }
    elseif (-not [IO.Path]::IsPathRooted($models)) { $models = Join-Path $root $models }
    Invoke-Checked $mlPython @('ml2/scripts/download_models.py', '--source', $models, '--verify-only') $root 'Prepare weights: ml2/.venv/Scripts/python.exe ml2/scripts/download_models.py --download; or set ML_MODELS_DIR to a verified local bundle.'
    $overrides = @{
        PIPELINE_MODE = 'live'; ML1_URL = 'http://127.0.0.1:8001'; ML2_URL = 'http://127.0.0.1:8002'
        RULES_PATH = (Join-Path $root 'data/rules.json'); ML_MODELS_DIR = $models
        HF_HUB_OFFLINE = '1'; TRANSFORMERS_OFFLINE = '1'; HF_HUB_DISABLE_TELEMETRY = '1'; DO_NOT_TRACK = '1'
        PYTHONUNBUFFERED = '1'; PYTHONUTF8 = '1'; STORAGE_DIR = (Join-Path $root 'work/stack/storage')
    }
    foreach ($name in $overrides.Keys) {
        if (-not $savedEnvironment.ContainsKey($name)) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
        [Environment]::SetEnvironmentVariable($name, $overrides[$name], 'Process')
    }

    $eventName = 'Local\CashierGuardStack-' + [Guid]::NewGuid().ToString('N')
    $stopEvent = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, $eventName)
    $job = New-Object CashierGuard.WindowsStackJob
    $children = @()
    foreach ($spec in @(
        @{ name = 'ml1'; python = $mlPython; module = 'service.app:app'; port = 8001; directory = 'ml2' },
        @{ name = 'matching'; python = $mlPython; module = 'matching.app:app'; port = 8002; directory = 'ml2' },
        @{ name = 'backend'; python = $backendPython; module = 'app.main:app'; port = 8000; directory = 'backend' }
    )) {
        $argv = @($spec.python, '-m', 'uvicorn', $spec.module, '--host', '127.0.0.1', '--port', [string]$spec.port, '--workers', '1', '--no-access-log')
        $commandLine = ($argv | ForEach-Object { Quote-NativeArgument $_ }) -join ' '
        $childId = $job.Start($spec.python, $commandLine, (Join-Path $root $spec.directory),
            (Join-Path $stackDir ($spec.name + '.out.log')), (Join-Path $stackDir ($spec.name + '.err.log')))
        $children += $childId
    }
    $state = @{ owner_pid = $PID; owner_started = (Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks.ToString(); stop_event = $eventName; children = $children }
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    $ownsState = $true

    $until = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    $ready = $null
    while ([DateTime]::UtcNow -lt $until) {
        if ($stopEvent.WaitOne(200)) { return }
        foreach ($childId in $children) {
            if ($null -eq (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { throw 'A service exited during startup. See work/stack/*.err.log.' }
        }
        try {
            $ml1 = Invoke-RestMethod 'http://127.0.0.1:8001/health' -TimeoutSec 2
            $ml2 = Invoke-RestMethod 'http://127.0.0.1:8002/health' -TimeoutSec 2
            $candidate = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ready' -TimeoutSec 2
            if ($ml1.status -eq 'ok' -and $ml2.status -eq 'ok' -and $candidate.ready -eq $true -and $candidate.mode -eq 'live') {
                $ready = $candidate; break
            }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if ($null -eq $ready) { throw 'Readiness timeout: require ML1/matching health and backend ready=true, mode=live. See work/stack/*.err.log and /api/v1/ready.' }
    Write-Host 'Ready: http://127.0.0.1:8000 (live). Logs: work/stack/. API key: root .env, never printed.'
    Write-Host 'No enabled detector rules: no_violation means no observations; it does not establish compliance.'
    if ($Check) { Write-Host 'Check complete; stopping all process trees owned by this launcher.'; return }
    Write-Host 'Ctrl+C here, or scripts/start-stack.ps1 -Stop in another PowerShell, stops this stack only.'
    while (-not $stopEvent.WaitOne(250)) {
        foreach ($childId in $children) {
            if ($null -eq (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { throw 'A service exited. See work/stack/*.err.log.' }
        }
    }
} finally {
    if ($null -ne $job) { $job.Dispose() }
    if ($ownsState -and (Test-Path -LiteralPath $statePath)) { Remove-Item -LiteralPath $statePath }
    if ($null -ne $stopEvent) { $stopEvent.Dispose() }
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if ($null -ne $lock) { $lock.Dispose() }
}
