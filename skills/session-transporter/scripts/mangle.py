#!/usr/bin/env python3
"""Reimplementation of Claude Code 2.1.215 project-dir mangler `Pw`, derived from the
bundled JS in the ELF at offset 239728033:

    function bzm(e){return Math.abs(nQe(e)).toString(36)}
    function Pw(e){let t=e.replace(/[^a-zA-Z0-9]/g,"-");
                   if(t.length<=Jvt)return t;
                   return `${t.slice(0,Jvt)}-${bzm(e)}`}      // Jvt = 200
    function nQe(e){let t=0;for(let r=0;r<e.length;r++)t=(t<<5)-t+e.charCodeAt(r)|0;return t}
"""
import re, sys

MAX = 200

def java_hash_utf16(s: str) -> int:
    """nQe: h = (h*31 + code_unit) as int32.  charCodeAt => UTF-16 code units."""
    u16 = s.encode('utf-16-le')
    h = 0
    for i in range(0, len(u16), 2):
        c = u16[i] | (u16[i + 1] << 8)
        h = (h * 31 + c) & 0xFFFFFFFF
        if h >= 0x80000000:            # | 0  -> signed 32-bit
            h -= 0x100000000
    return h

def to_base36(n: int) -> str:
    if n == 0:
        return '0'
    d = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = ''
    while n:
        out = d[n % 36] + out
        n //= 36
    return out

def sanitize(path: str) -> str:
    """The [^a-zA-Z0-9] -> '-' pass, applied per UTF-16 code unit (JS semantics)."""
    out = []
    u16 = path.encode('utf-16-le')
    for i in range(0, len(u16), 2):
        c = u16[i] | (u16[i + 1] << 8)
        ch = chr(c)
        out.append(ch if ('a' <= ch <= 'z' or 'A' <= ch <= 'Z' or '0' <= ch <= '9') else '-')
    return ''.join(out)

def mangle(path: str) -> str:
    t = sanitize(path)
    if len(t) <= MAX:
        return t
    return t[:MAX] + '-' + to_base36(abs(java_hash_utf16(path)))

if __name__ == '__main__':
    for p in sys.argv[1:]:
        print(mangle(p))
