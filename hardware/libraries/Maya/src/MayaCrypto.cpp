#include "MayaCrypto.h"

#include <string.h>

namespace mayalib {

namespace {

const uint32_t K[64] = {
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

inline uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

struct Ctx {
  uint32_t h[8];
  uint8_t buf[64];
  size_t used;
  uint64_t total;
};

void block(Ctx& c, const uint8_t* p) {
  uint32_t w[64];
  for (int i = 0; i < 16; i++)
    w[i] = (uint32_t)p[i * 4] << 24 | (uint32_t)p[i * 4 + 1] << 16 | (uint32_t)p[i * 4 + 2] << 8 | p[i * 4 + 3];
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
    uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  uint32_t a = c.h[0], b = c.h[1], cc = c.h[2], d = c.h[3], e = c.h[4], f = c.h[5], g = c.h[6], h = c.h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
    uint32_t ch = (e & f) ^ (~e & g);
    uint32_t t1 = h + S1 + ch + K[i] + w[i];
    uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
    uint32_t maj = (a & b) ^ (a & cc) ^ (b & cc);
    uint32_t t2 = S0 + maj;
    h = g; g = f; f = e; e = d + t1; d = cc; cc = b; b = a; a = t1 + t2;
  }
  c.h[0] += a; c.h[1] += b; c.h[2] += cc; c.h[3] += d;
  c.h[4] += e; c.h[5] += f; c.h[6] += g; c.h[7] += h;
}

void init(Ctx& c) {
  static const uint32_t H0[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  memcpy(c.h, H0, sizeof H0);
  c.used = 0;
  c.total = 0;
}

void update(Ctx& c, const uint8_t* data, size_t len) {
  c.total += len;
  while (len) {
    size_t n = 64 - c.used;
    if (n > len) n = len;
    memcpy(c.buf + c.used, data, n);
    c.used += n; data += n; len -= n;
    if (c.used == 64) { block(c, c.buf); c.used = 0; }
  }
}

void finish(Ctx& c, uint8_t out[32]) {
  uint64_t bits = c.total * 8;
  uint8_t pad = 0x80;
  update(c, &pad, 1);
  uint8_t zero = 0;
  while (c.used != 56) update(c, &zero, 1);
  uint8_t lenBytes[8];
  for (int i = 0; i < 8; i++) lenBytes[i] = (uint8_t)(bits >> (56 - 8 * i));
  update(c, lenBytes, 8);
  for (int i = 0; i < 8; i++) {
    out[i * 4] = (uint8_t)(c.h[i] >> 24); out[i * 4 + 1] = (uint8_t)(c.h[i] >> 16);
    out[i * 4 + 2] = (uint8_t)(c.h[i] >> 8); out[i * 4 + 3] = (uint8_t)c.h[i];
  }
}

}  // namespace

void sha256(const uint8_t* data, size_t len, uint8_t out[32]) {
  Ctx c; init(c); update(c, data, len); finish(c, out);
}

void hmacSha256(const uint8_t* key, size_t keyLen, const uint8_t* msg, size_t msgLen, uint8_t out[32]) {
  uint8_t k[64] = {0};
  if (keyLen > 64) sha256(key, keyLen, k);
  else memcpy(k, key, keyLen);
  uint8_t ipad[64], opad[64];
  for (int i = 0; i < 64; i++) { ipad[i] = k[i] ^ 0x36; opad[i] = k[i] ^ 0x5c; }
  uint8_t inner[32];
  Ctx c;
  init(c); update(c, ipad, 64); update(c, msg, msgLen); finish(c, inner);
  init(c); update(c, opad, 64); update(c, inner, 32); finish(c, out);
}

int base64Decode(const char* in, size_t inLen, uint8_t* out, size_t outCap) {
  if (inLen % 4 != 0) return -1;
  size_t o = 0;
  for (size_t i = 0; i < inLen; i += 4) {
    int v[4];
    int pad = 0;
    for (int j = 0; j < 4; j++) {
      char ch = in[i + j];
      if (ch >= 'A' && ch <= 'Z') v[j] = ch - 'A';
      else if (ch >= 'a' && ch <= 'z') v[j] = ch - 'a' + 26;
      else if (ch >= '0' && ch <= '9') v[j] = ch - '0' + 52;
      else if (ch == '+') v[j] = 62;
      else if (ch == '/') v[j] = 63;
      else if (ch == '=' && i + 4 == inLen && j >= 2) { v[j] = 0; pad++; }
      else return -1;
    }
    if (pad == 1 && in[i + 2] == '=') return -1;   // "=" may only follow a char, "==" only at the end
    size_t need = 3 - pad;
    if (o + need > outCap) return -1;
    uint32_t n = (uint32_t)v[0] << 18 | (uint32_t)v[1] << 12 | (uint32_t)v[2] << 6 | (uint32_t)v[3];
    out[o++] = (uint8_t)(n >> 16);
    if (need > 1) out[o++] = (uint8_t)(n >> 8);
    if (need > 2) out[o++] = (uint8_t)n;
  }
  return (int)o;
}

size_t base64UrlEncode(const uint8_t* in, size_t n, char* out, size_t outCap) {
  static const char A[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  size_t o = 0;
  for (size_t i = 0; i < n; i += 3) {
    uint32_t v = (uint32_t)in[i] << 16;
    if (i + 1 < n) v |= (uint32_t)in[i + 1] << 8;
    if (i + 2 < n) v |= in[i + 2];
    int chars = (i + 2 < n) ? 4 : (i + 1 < n) ? 3 : 2;
    if (o + chars + 1 > outCap) { if (outCap) out[0] = 0; return 0; }
    out[o++] = A[(v >> 18) & 63];
    out[o++] = A[(v >> 12) & 63];
    if (chars > 2) out[o++] = A[(v >> 6) & 63];
    if (chars > 3) out[o++] = A[v & 63];
  }
  out[o] = 0;
  return o;
}

bool constantTimeEqual(const uint8_t* a, const uint8_t* b, size_t n) {
  uint8_t diff = 0;
  for (size_t i = 0; i < n; i++) diff |= a[i] ^ b[i];
  return diff == 0;
}

uint32_t parseIsoUtc(const char* s) {
  if (!s || strlen(s) != 20 || s[4] != '-' || s[7] != '-' || s[10] != 'T' || s[13] != ':'
      || s[16] != ':' || s[19] != 'Z')
    return 0;
  auto d2 = [](const char* p) { return (p[0] - '0') * 10 + (p[1] - '0'); };
  static const int DIGITS[] = {0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18};
  for (int i : DIGITS)
    if (s[i] < '0' || s[i] > '9') return 0;
  int year = d2(s) * 100 + d2(s + 2), mon = d2(s + 5), day = d2(s + 8);
  int hh = d2(s + 11), mm = d2(s + 14), ss = d2(s + 17);
  if (year < 1970 || year > 2105 || mon < 1 || mon > 12 || day < 1 || day > 31 || hh > 23 || mm > 59 || ss > 60)
    return 0;
  // days from civil (Howard Hinnant's algorithm)
  int y = year - (mon <= 2);
  int era = y / 400;
  int yoe = y - era * 400;
  int doy = (153 * (mon + (mon > 2 ? -3 : 9)) + 2) / 5 + day - 1;
  int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  // 64-bit: `long` is 32 bits on the ESP32, and days*86400 passes 2^31 in 2038.
  int64_t days = (int64_t)era * 146097 + doe - 719468;
  int64_t secs = days * 86400 + hh * 3600 + mm * 60 + ss;
  return secs > 0xFFFFFFFFLL ? 0xFFFFFFFFu : (uint32_t)secs;
}

}  // namespace mayalib
