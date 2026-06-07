package lock

import (
	"path/filepath"
	"testing"
)

func TestPortLeaseAcquireRelease(t *testing.T) {
	dir := t.TempDir()
	reg := NewPortRegistry(filepath.Join(dir, "ports.json"), 41000, 41010)
	port, err := reg.Acquire("agent-a")
	if err != nil {
		t.Fatal(err)
	}
	if port < 41000 || port > 41010 {
		t.Fatalf("port out of range: %d", port)
	}
	if err := reg.Release(port); err != nil {
		t.Fatal(err)
	}
	port2, err := reg.Acquire("agent-b")
	if err != nil {
		t.Fatal(err)
	}
	if port2 == 0 {
		t.Fatal("expected port after release")
	}
}
