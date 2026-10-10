// The few primitives the local link needs (PROTOCOL.md 7.2), written out so the
// protocol core still builds on a laptop and a test can check them against
// Python's hashlib/hmac. On the ESP32 they cost ~1 KB of flash; mbedtls is there
// too, but one implementation that is tested on both sides is worth more than a
// faster one that is tested on one.
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace mayalib {

void sha256(const uint8_t* data, size_t len, uint8_t out[32]);
void hmacSha256(const uint8_t* key, size_t keyLen, const uint8_t* msg, size_t msgLen,
                uint8_t out[32]);

// Standard base64 (RFC 4648 section 4), with padding. Returns bytes written, or
// -1 if the input is not valid base64 or does not fit.
int base64Decode(const char* in, size_t inLen, uint8_t* out, size_t outCap);

// base64url without padding (RFC 4648 section 5): what the frame MAC is written in.
// Writes a terminator; `outCap` must hold ceil(n*4/3)+1. Returns characters written.
size_t base64UrlEncode(const uint8_t* in, size_t n, char* out, size_t outCap);

// Equal, in time that does not depend on where the first difference is.
bool constantTimeEqual(const uint8_t* a, const uint8_t* b, size_t n);

// "2026-11-09T15:41:16Z" -> seconds since 1970, or 0 if it is not that shape.
uint32_t parseIsoUtc(const char* s);

}  // namespace mayalib
