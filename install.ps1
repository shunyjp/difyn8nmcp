#Requires -Version 5.1
<#
.SYNOPSIS
    MCP Server Setup Script for n8n / Dify / GitHub
.USAGE
    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
    .\install.ps1
#>

$ErrorActionPreference = "Stop"
$MCP_DIR     = "$env:USERPROFILE\Downloads\AI ITトレンド情報収集\mcp"
$CLAUDE_JSON = "$env:USERPROFILE\.claude.json"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  MCP Server Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "  OK: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# Step 2: Install pip packages
Write-Host ""
Write-Host "[2/4] Installing Python packages..." -ForegroundColor Yellow
pip install "mcp[cli]" httpx pydantic --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK: mcp, httpx, pydantic installed" -ForegroundColor Green
} else {
    Write-Host "  ERROR: pip install failed." -ForegroundColor Red
    exit 1
}

# Step 3: Check Node.js
Write-Host ""
Write-Host "[3/4] Checking Node.js (for GitHub MCP)..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version 2>&1
    Write-Host "  OK: Node.js $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "  WARN: Node.js not found. GitHub MCP will be skipped." -ForegroundColor Yellow
    Write-Host "        Install from https://nodejs.org if needed." -ForegroundColor Yellow
}

# Step 4: Register MCPs in Claude Code
Write-Host ""
Write-Host "[4/4] Registering MCP servers in Claude Code..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Enter your GitHub Personal Access Token." -ForegroundColor Cyan
Write-Host "  Get one at: https://github.com/settings/tokens (repo + workflow scopes)" -ForegroundColor Gray
Write-Host "  Press Enter to skip GitHub MCP." -ForegroundColor Gray
$githubPat = Read-Host "  GitHub PAT"

# Read .env
$envFile = Join-Path $MCP_DIR ".env"
$envVars = @{}
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match "^[^#].+=.+" } | ForEach-Object {
        $parts = $_ -split "=", 2
        $envVars[$parts[0].Trim()] = $parts[1].Trim()
    }
}

$n8nApiKey = $envVars["N8N_API_KEY"]
$difyEmail  = $envVars["DIFY_EMAIL"]
$difyPass   = $envVars["DIFY_PASSWORD"]
$n8nUrl     = $envVars["N8N_BASE_URL"]
$difyUrl    = $envVars["DIFY_BASE_URL"]

$n8nScript  = Join-Path $MCP_DIR "n8n_mcp\server.py"
$difyScript = Join-Path $MCP_DIR "dify_mcp\server.py"

# Build mcpServers object
$mcpServers = [ordered]@{
    n8n = [ordered]@{
        type    = "stdio"
        command = "python"
        args    = @($n8nScript)
        env     = [ordered]@{
            N8N_BASE_URL = $n8nUrl
            N8N_API_KEY  = $n8nApiKey
        }
    }
    dify = [ordered]@{
        type    = "stdio"
        command = "python"
        args    = @($difyScript)
        env     = [ordered]@{
            DIFY_BASE_URL = $difyUrl
            DIFY_EMAIL    = $difyEmail
            DIFY_PASSWORD = $difyPass
        }
    }
}

if ($githubPat -ne "") {
    $mcpServers["github"] = [ordered]@{
        type    = "stdio"
        command = "npx"
        args    = @("-y", "@modelcontextprotocol/server-github")
        env     = [ordered]@{
            GITHUB_PERSONAL_ACCESS_TOKEN = $githubPat
        }
    }
    Write-Host "  GitHub MCP will be registered." -ForegroundColor Green
}

# Load or create claude.json
if (Test-Path $CLAUDE_JSON) {
    $claudeConfig = Get-Content $CLAUDE_JSON -Raw | ConvertFrom-Json
    $configHash = @{}
    $claudeConfig.PSObject.Properties | ForEach-Object { $configHash[$_.Name] = $_.Value }
} else {
    $configHash = @{}
}

if (-not $configHash.ContainsKey("mcpServers")) {
    $configHash["mcpServers"] = @{}
}

foreach ($key in $mcpServers.Keys) {
    $configHash["mcpServers"] | Add-Member -NotePropertyName $key -NotePropertyValue $mcpServers[$key] -Force
}

$configHash | ConvertTo-Json -Depth 10 | Set-Content $CLAUDE_JSON -Encoding UTF8
Write-Host "  OK: Written to $CLAUDE_JSON" -ForegroundColor Green

# Done
$testScript = Join-Path $MCP_DIR "test_connection.py"
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart Claude Code." -ForegroundColor White
Write-Host "  2. Try: n8n workflow list" -ForegroundColor White
Write-Host "  3. Try: Dify app list" -ForegroundColor White
Write-Host ""
Write-Host "  To test connection first, run:" -ForegroundColor White
Write-Host "  python $testScript" -ForegroundColor Gray
Write-Host ""
