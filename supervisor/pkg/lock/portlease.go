package lock

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

type portEntry struct {
	Owner string `json:"owner"`
	Port  int    `json:"port"`
}

type portFile struct {
	Leases map[string]portEntry `json:"leases"`
}

// PortRegistry 管理端口租约，持久化到 JSON 文件。
type PortRegistry struct {
	mu    sync.Mutex
	path  string
	min   int
	max   int
	leases map[int]portEntry
}

func NewPortRegistry(path string, minPort, maxPort int) *PortRegistry {
	reg := &PortRegistry{
		path:   path,
		min:    minPort,
		max:    maxPort,
		leases: make(map[int]portEntry),
	}
	_ = reg.load()
	return reg
}

func (r *PortRegistry) load() error {
	data, err := os.ReadFile(r.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	var pf portFile
	if err := json.Unmarshal(data, &pf); err != nil {
		return err
	}
	if pf.Leases == nil {
		return nil
	}
	for key, entry := range pf.Leases {
		var port int
		if _, err := fmt.Sscanf(key, "%d", &port); err == nil {
			r.leases[port] = entry
		}
	}
	return nil
}

func (r *PortRegistry) save() error {
	if err := os.MkdirAll(filepath.Dir(r.path), 0o755); err != nil {
		return err
	}
	pf := portFile{Leases: make(map[string]portEntry)}
	for port, entry := range r.leases {
		pf.Leases[fmt.Sprintf("%d", port)] = entry
	}
	data, err := json.MarshalIndent(pf, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(r.path, data, 0o644)
}

// Acquire 分配一个空闲端口给 owner。
func (r *PortRegistry) Acquire(owner string) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	for port := r.min; port <= r.max; port++ {
		if _, used := r.leases[port]; !used {
			r.leases[port] = portEntry{Owner: owner, Port: port}
			if err := r.save(); err != nil {
				delete(r.leases, port)
				return 0, err
			}
			return port, nil
		}
	}
	return 0, fmt.Errorf("no free port in range %d-%d", r.min, r.max)
}

// Release 释放端口。
func (r *PortRegistry) Release(port int) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.leases[port]; !ok {
		return fmt.Errorf("port %d not leased", port)
	}
	delete(r.leases, port)
	return r.save()
}
