// Package negative is the failing twin of the positive Go fixture.
package negative

// Checksum sums the bytes of s modulo 256.
func Checksum(s string) int {
	total := 0
	for _, b := range []byte(s) {
		total += int(b)
	}
	return total % 256
}
