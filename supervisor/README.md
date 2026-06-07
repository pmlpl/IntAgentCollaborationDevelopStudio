# Build Go supervisor (requires Go 1.22+ and protoc with go plugins):
#   cd supervisor
#   protoc --go_out=. --go-grpc_out=. api/supervisor.proto
#   go build -o bin/studio-supervisor.exe ./cmd/studio-supervisor
#
# Phase 1 fallback: Python registry in core/supervisor/registry.py
