# Run with the active ML Python 3.12 environment; all arguments go to run_chain.py.
$ErrorActionPreference = 'Stop'
python (Join-Path $PSScriptRoot 'run_chain.py') @args
exit $LASTEXITCODE
