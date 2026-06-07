// Package main 是 Studio 平台 Go 调度守护进程入口。
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	pb "studio/supervisor/api"
	"studio/supervisor/pkg/lock"
	"studio/supervisor/pkg/process"

	"google.golang.org/grpc"
)

type supervisorService struct {
	pb.UnimplementedSupervisorServer
	ports *lock.PortRegistry
	procs *process.Registry
}

func (s *supervisorService) Health(context.Context, *pb.HealthRequest) (*pb.HealthResponse, error) {
	return &pb.HealthResponse{Ok: true}, nil
}

func (s *supervisorService) AcquirePort(_ context.Context, req *pb.AcquirePortRequest) (*pb.AcquirePortResponse, error) {
	port, err := s.ports.Acquire(req.GetOwner())
	if err != nil {
		return nil, err
	}
	return &pb.AcquirePortResponse{Port: int32(port)}, nil
}

func (s *supervisorService) ReleasePort(_ context.Context, req *pb.ReleasePortRequest) (*pb.ReleasePortResponse, error) {
	if err := s.ports.Release(int(req.GetPort())); err != nil {
		return nil, err
	}
	return &pb.ReleasePortResponse{Ok: true}, nil
}

func (s *supervisorService) SpawnAgent(_ context.Context, req *pb.SpawnAgentRequest) (*pb.SpawnAgentResponse, error) {
	if s.procs.IsAlive(req.GetPositionId()) {
		return nil, fmt.Errorf("position %s already has active worker", req.GetPositionId())
	}
	// Phase 1: 仅注册占位 PID，实际 spawn 由 Python adapter 完成
	pid := os.Getpid()
	started := time.Now().UTC().Format(time.RFC3339)
	if err := s.procs.Register(req.GetPositionId(), pid, started); err != nil {
		return nil, err
	}
	return &pb.SpawnAgentResponse{Pid: int32(pid)}, nil
}

func (s *supervisorService) KillAgent(_ context.Context, req *pb.KillAgentRequest) (*pb.KillAgentResponse, error) {
	if err := s.procs.Unregister(req.GetPositionId()); err != nil {
		return nil, err
	}
	return &pb.KillAgentResponse{Ok: true}, nil
}

func main() {
	root := flag.String("root", ".", "studio root directory")
	addr := flag.String("addr", "127.0.0.1:42000", "gRPC listen address")
	flag.Parse()

	studioRoot, err := filepath.Abs(*root)
	if err != nil {
		log.Fatal(err)
	}

	studioDir := filepath.Join(studioRoot, ".studio")
	registryDir := filepath.Join(studioDir, "registry")
	if err := os.MkdirAll(registryDir, 0o755); err != nil {
		log.Fatal(err)
	}

	pidPath := filepath.Join(studioDir, "supervisor.pid")
	if err := os.WriteFile(pidPath, []byte(strconv.Itoa(os.Getpid())), 0o644); err != nil {
		log.Fatal(err)
	}

	ports := lock.NewPortRegistry(filepath.Join(registryDir, "ports.json"), 41000, 41999)
	procs := process.NewRegistry(filepath.Join(registryDir, "processes.json"))

	lis, err := net.Listen("tcp", *addr)
	if err != nil {
		log.Fatal(err)
	}

	srv := grpc.NewServer()
	pb.RegisterSupervisorServer(srv, &supervisorService{ports: ports, procs: procs})

	go func() {
		log.Printf("studio-supervisor listening on %s", *addr)
		if err := srv.Serve(lis); err != nil {
			log.Fatal(err)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	srv.GracefulStop()
	_ = os.Remove(pidPath)
}
