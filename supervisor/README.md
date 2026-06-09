# Studio Supervisor (Go)

Go 调度守护进程：端口租约、进程注册、gRPC API。

## 前置依赖

- Go 1.22+（已安装：`go version`）
- protoc（`winget install Google.Protobuf`）

## 编译

```powershell
cd supervisor

# 国内网络建议设置代理
$env:GOPROXY = "https://goproxy.cn,direct"

# 安装 protoc 插件（首次）
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.34.2
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.5.1

# 生成 gRPC 代码并编译
protoc --go_out=. --go_opt=paths=source_relative `
       --go-grpc_out=. --go-grpc_opt=paths=source_relative `
       api/supervisor.proto
go mod tidy
go build -o bin/studio-supervisor.exe ./cmd/studio-supervisor
```

产物路径：

```
supervisor/bin/studio-supervisor.exe
```

## 运行

```powershell
.\bin\studio-supervisor.exe --root "C:\path\to\IntAgentCollaborationDevelopStudio"
```

默认监听 `127.0.0.1:42000`，写入 `.studio/supervisor.pid` 与 `.studio/registry/`。

## 测试

```powershell
go test ./...
```

## Python 回退

若未编译 Go 二进制，`core/supervisor/registry.py` 提供等效的 Python 注册表实现。
