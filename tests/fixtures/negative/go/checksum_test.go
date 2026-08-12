package negative

import "testing"

// TestChecksumIsDeliberatelyWrong asserts a value the implementation cannot
// produce, so `go test ./...` must fail. If this test ever passes, go-ci has
// stopped reporting test failures.
func TestChecksumIsDeliberatelyWrong(t *testing.T) {
	if got := Checksum("ci"); got != 999 {
		t.Fatalf("deliberate failure: Checksum(\"ci\") = %d, fixture asserts 999", got)
	}
}
