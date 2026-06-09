# Windows 一键编译 studio-supervisor.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:GOPROXY = if ($env:GOPROXY) { $env:GOPROXY } else { "https://goproxy.cn,direct" }

New-Item -ItemType Directory -Force -Path bin | Out-Null

protoc --go_out=. --go_opt=paths=source_relative `
       --go-grpc_out=. --go-grpc_opt=paths=source_relative `
       api/supervisor.proto

go mod tidy
go test ./...
go build -o bin/studio-supervisor.exe ./cmd/studio-supervisor

Write-Host "Built: $(Resolve-Path bin/studio-supervisor.exe)"
