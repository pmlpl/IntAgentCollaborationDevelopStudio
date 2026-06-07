package process

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"syscall"
)

type procEntry struct {
	PositionID string `json:"position_id"`
	PID        int    `json:"pid"`
	StartedAt  string `json:"started_at"`
}

type procFile struct {
	Processes map[string]procEntry `json:"processes"`
}

// Registry 记录 position 到 PID 的映射。
type Registry struct {
	mu       sync.Mutex
	path     string
	processes map[string]procEntry
}

func NewRegistry(path string) *Registry {
	reg := &Registry{
		path:      path,
		processes: make(map[string]procEntry),
	}
	_ = reg.load()
	return reg
}

func (r *Registry) load() error {
	data, err := os.ReadFile(r.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	var pf procFile
	if err := json.Unmarshal(data, &pf); err != nil {
		return err
	}
	if pf.Processes != nil {
		r.processes = pf.Processes
	}
	return nil
}

func (r *Registry) save() error {
	if err := os.MkdirAll(filepath.Dir(r.path), 0o755); err != nil {
		return err
	}
	pf := procFile{Processes: r.processes}
	data, err := json.MarshalIndent(pf, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(r.path, data, 0o644)
}

func (r *Registry) Register(positionID string, pid int, startedAt string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.processes[positionID] = procEntry{
		PositionID: positionID,
		PID:        pid,
		StartedAt:  startedAt,
	}
	return r.save()
}

func (r *Registry) Unregister(positionID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.processes, positionID)
	return r.save()
}

func (r *Registry) IsAlive(positionID string) bool {
	r.mu.Lock()
	entry, ok := r.processes[positionID]
	r.mu.Unlock()
	if !ok {
		return false
	}
	proc, err := os.FindProcess(entry.PID)
	if err != nil {
		return false
	}
	err = proc.Signal(syscall.Signal(0))
	return err == nil
}

func (r *Registry) Get(positionID string) (procEntry, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	e, ok := r.processes[positionID]
	return e, ok
}

func (r *Registry) String() string {
	return fmt.Sprintf("%d processes", len(r.processes))
}
