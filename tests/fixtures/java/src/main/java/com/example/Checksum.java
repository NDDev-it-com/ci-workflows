package com.example;

/** Smallest class that gives the compiler and the packaging lane real work. */
public final class Checksum {

    private Checksum() {
    }

    /** Sums the bytes of {@code text} modulo 256. */
    public static int of(String text) {
        int total = 0;
        for (byte b : text.getBytes(java.nio.charset.StandardCharsets.UTF_8)) {
            total += b & 0xFF;
        }
        return total % 256;
    }

    public static void main(String[] args) {
        if (of("ci") != 204 || of("") != 0) {
            throw new AssertionError("checksum fixture failed");
        }
        System.out.println("checksum fixture ok");
    }
}
