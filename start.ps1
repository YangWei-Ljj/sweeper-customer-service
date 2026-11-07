# 扫地机器人客服 · Windows 一键启动（Streamlit :8513，默认本地 Ollama）
# 首次使用建议：python scripts/rebuild_knowledge.py --full 重建本地知识库（172 块）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = "python"
if (-not (Test-Path $py)) { $py = "python" }

function Test-Port([int]$p) { [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "已从 .env.example 生成 .env（默认 ollama 模式）" -ForegroundColor Yellow
}

Write-Host "初始化数据库 ..." -ForegroundColor Cyan
& $py scripts\init_db.py

if (Test-Port 8513) {
    Write-Host "端口 8513 已被占用，视为已在运行（http://localhost:8513）" -ForegroundColor Yellow
    Read-Host "按回车结束"
    exit 0
}
Write-Host "启动 Streamlit（http://localhost:8513）..." -ForegroundColor Cyan
& $py -m streamlit run app.py --server.port 8513 --server.headless true