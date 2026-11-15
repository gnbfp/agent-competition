# -*- coding: utf-8 -*-
"""Minimal PDF text extractor (stdlib only): ASCII85/Flate streams, simple
TrueType/CID fonts with ToUnicode CMaps, octal escapes in literal strings."""
import re, zlib, sys, os, base64

def load_objects(data):
    objs = {}
    for m in re.finditer(rb'(?<![0-9])(\d+)\s+(\d+)\s+obj\b', data):
        num = int(m.group(1))
        start = m.end()
        if num in objs:
            continue
        sm = re.compile(rb'stream\r?\n').search(data, start)
        eo = data.find(b'endobj', start)
        if sm is not None and (eo == -1 or sm.start() < eo):
            head = data[start:sm.start()]
            est = data.find(b'endstream', sm.end())
            raw = data[sm.end():est] if est != -1 else data[sm.end():eo]
            objs[num] = (head, raw)
        else:
            objs[num] = (data[start:eo], None)
    return objs

def _filters(head):
    m = re.search(rb'/Filter\s*\[([^\]]*)\]', head)
    if m:
        return re.findall(rb'/(\w+)', m.group(1))
    m = re.search(rb'/Filter\s*/(\w+)', head)
    return [m.group(1)] if m else []

def decode_stream(head, raw):
    if raw is None:
        return None
    fl = _filters(head)
    out = raw
    for f in fl:
        if f in (b'ASCII85Decode', b'A85'):
            s = out
            if s.startswith(b'<~'):
                s = s[2:]
            i = s.find(b'~>')
            if i != -1:
                s = s[:i]
            s = re.sub(rb'\s', b'', s)
            try:
                out = base64.a85decode(s + b'~>', adobe=True)
            except Exception:
                out = base64.a85decode(s, adobe=False)
        elif f in (b'FlateDecode', b'Fl'):
            try:
                out = zlib.decompress(out)
            except Exception:
                try:
                    out = zlib.decompressobj().decompress(out)
                except Exception:
                    return None
        elif f in (b'ASCIIHexDecode', b'AHx'):
            s = re.sub(rb'\s', b'', out).rstrip(b'>')
            out = bytes.fromhex(s.decode())
        elif f in (b'LZWDecode', b'RLDecode'):
            return None
    return out

def stream_bytes(objs, num):
    if num not in objs:
        return None
    head, raw = objs[num]
    return decode_stream(head, raw)

def parse_cmap(text):
    cmap = {}
    codelen = None
    for blk in re.finditer(rb'beginbfchar(.*?)endbfchar', text, re.S):
        for m in re.finditer(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk.group(1)):
            src = m.group(1).decode(); dst = m.group(2).decode()
            try:
                code = int(src, 16)
                s = bytes.fromhex(dst if len(dst) % 2 == 0 else dst + '0').decode('utf-16-be', 'ignore')
            except Exception:
                continue
            cmap[code] = s
            codelen = max(codelen or 1, len(src) // 2)
    for blk in re.finditer(rb'beginbfrange(.*?)endbfrange', text, re.S):
        body = blk.group(1)
        for m in re.finditer(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])', body):
            lo = int(m.group(1), 16); hi = int(m.group(2), 16); dst = m.group(3)
            codelen = max(codelen or 1, len(m.group(1)) // 2)
            if dst.startswith(b'<'):
                base = dst[1:-1].decode()
                baseb = bytes.fromhex(base if len(base) % 2 == 0 else base + '0')
                b0 = int.from_bytes(baseb, 'big')
                for i in range(hi - lo + 1):
                    try:
                        cmap[lo + i] = (b0 + i).to_bytes(len(baseb), 'big').decode('utf-16-be', 'ignore')
                    except Exception:
                        pass
            else:
                for i, h in enumerate(re.findall(rb'<([0-9A-Fa-f]+)>', dst)):
                    if lo + i > hi:
                        break
                    hh = h.decode()
                    try:
                        cmap[lo + i] = bytes.fromhex(hh if len(hh) % 2 == 0 else hh + '0').decode('utf-16-be', 'ignore')
                    except Exception:
                        pass
    return cmap, codelen

class Font:
    def __init__(self, cmap=None, codelen=1, base=b''):
        self.cmap = cmap or {}
        self.codelen = codelen
        self.base = base

def build_fonts(objs):
    fonts = {}
    for num, (head, raw) in objs.items():
        if not re.search(rb'/Type\s*/Font', head) and b'/BaseFont' not in head:
            continue
        cmap, cl = {}, 1
        tu = re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', head)
        if tu:
            s = stream_bytes(objs, int(tu.group(1)))
            if s:
                cmap, cl = parse_cmap(s)
                cl = cl or 1
        bm = re.search(rb'/BaseFont\s*/([^\s/>]+)', head)
        fonts[num] = Font(cmap, cl, bm.group(1) if bm else b'')
    return fonts

def _is_font_obj(objs, n):
    return n in objs and (re.search(rb'/Type\s*/Font', objs[n][0]) is not None
                          or b'/BaseFont' in objs[n][0])

def _dict_pairs(body):
    return [(m.group(1).decode(), int(m.group(2)))
            for m in re.finditer(rb'/([A-Za-z0-9_.+\-]+)\s+(\d+)\s+0\s+R', body)]

def page_font_map(head, objs, depth=0):
    out = {}
    # 1) /Font <</Fx n 0 R>> inline
    m = re.search(rb'/Font\s*<<(.*?)>>', head, re.S)
    if m:
        for name, n in _dict_pairs(m.group(1)):
            out[name] = n
    # 2) /Font n 0 R -> resource dict or font dict
    m = re.search(rb'/Font\s+(\d+)\s+0\s+R', head)
    if m and depth < 3:
        n = int(m.group(1))
        if _is_font_obj(objs, n):
            pass
        elif n in objs:
            out.update(page_font_map(objs[n][0], objs, depth + 1))
    # 3) a bare font-resource dict body: every /Name n 0 R whose target is a font
    if not out and depth < 3:
        for name, n in _dict_pairs(head):
            if _is_font_obj(objs, n):
                out[name] = n
    # 4) /Resources n 0 R
    m = re.search(rb'/Resources\s+(\d+)\s+0\s+R', head)
    if not out and m and depth < 3:
        n = int(m.group(1))
        if n in objs:
            out.update(page_font_map(objs[n][0], objs, depth + 1))
    return out

OCT = re.compile(rb'\\([0-7]{1,3}|.)', re.S)
ESC = {b'n': b'\n', b'r': b'\r', b't': b'\t', b'b': b'\b', b'f': b'\f',
       b'(': b'(', b')': b')', b'\\': b'\\'}

def unescape(bs):
    if b'\\' not in bs:
        return bs
    def rep(m):
        g = m.group(1)
        if re.fullmatch(rb'[0-7]{1,3}', g):
            return bytes([int(g, 8) & 0xFF])
        return ESC.get(g, g)
    return OCT.sub(rep, bs)

def decode_show(bs, font):
    if font is None:
        return bs.decode('latin-1', 'ignore')
    if font.cmap:
        step = font.codelen
        out = []
        for i in range(0, len(bs) - step + 1, step):
            code = int.from_bytes(bs[i:i + step], 'big')
            s = font.cmap.get(code)
            out.append(s if s is not None else '')
        return ''.join(out)
    return bs.decode('latin-1', 'ignore')

TOKEN = re.compile(
    rb'/([A-Za-z0-9_.+\-]+)\s+[\d.\-]+\s+Tf'          # 1 font
    rb'|\[((?:[^\[\]\\]|\\.)*)\]\s*TJ'               # 2 TJ array
    rb'|<([0-9A-Fa-f\s]*)>\s*Tj'                     # 3 hex string
    rb'|\(((?:[^()\\]|\\.)*)\)\s*Tj'                 # 4 literal string
    rb'|\(((?:[^()\\]|\\.)*)\)\s*[\'"]'              # 5 literal + move
    rb'|1\s+0\s+0\s+1\s+([\d.\-]+)\s+([\d.\-]+)\s+Tm'  # 6,7 Tm
    rb'|(T\*|Td|TD|ET|BT)', re.S)

def parse_content(content, fonts_map, fonts):
    parts = []
    cur = None
    last_y = None
    pending = []
    for m in TOKEN.finditer(content):
        if m.group(1) is not None:
            cur = fonts.get(fonts_map.get(m.group(1).decode()))
        elif m.group(2) is not None:
            arr = m.group(2)
            for tm in re.finditer(rb'<([0-9A-Fa-f\s]*)>|\(((?:[^()\\]|\\.)*)\)|(-?[\d.]+)', arr, re.S):
                if tm.group(1) is not None:
                    hx = re.sub(rb'\s', b'', tm.group(1)).decode()
                    try:
                        bs = bytes.fromhex(hx if len(hx) % 2 == 0 else hx + '0')
                    except Exception:
                        continue
                    parts.append(decode_show(bs, cur))
                elif tm.group(2) is not None:
                    parts.append(decode_show(unescape(tm.group(2)), cur))
                else:
                    try:
                        if float(tm.group(3)) <= -120:
                            parts.append(' ')
                    except Exception:
                        pass
        elif m.group(3) is not None:
            hx = re.sub(rb'\s', b'', m.group(3)).decode()
            try:
                bs = bytes.fromhex(hx if len(hx) % 2 == 0 else hx + '0')
            except Exception:
                continue
            parts.append(decode_show(bs, cur))
        elif m.group(4) is not None or m.group(5) is not None:
            parts.append(decode_show(unescape(m.group(4) if m.group(4) is not None else m.group(5)), cur))
        elif m.group(6) is not None:
            try:
                y = float(m.group(7))
            except Exception:
                y = None
            if last_y is not None and y is not None and abs(y - last_y) > 1.5:
                parts.append('\n')
            last_y = y if y is not None else last_y
        elif m.group(8) in (b'T*', b'ET'):
            if parts and not parts[-1].endswith('\n'):
                parts.append('\n')
    return ''.join(parts)

def extract(path, outdir):
    data = open(path, 'rb').read()
    objs = load_objects(data)
    fonts = build_fonts(objs)
    pages = [n for n in sorted(objs) if re.search(rb'/Type\s*/Page[^s]', objs[n][0])]
    chunks = []
    for pi, pnum in enumerate(pages, 1):
        head = objs[pnum][0]
        nums = []
        cm = re.search(rb'/Contents\s+(\d+)\s+0\s+R', head)
        if cm:
            nums = [int(cm.group(1))]
        else:
            am = re.search(rb'/Contents\s*\[(.*?)\]', head, re.S)
            if am:
                nums = [int(x) for x in re.findall(rb'(\d+)\s+0\s+R', am.group(1))]
        content = b''
        for cn in nums:
            s = stream_bytes(objs, cn)
            if s:
                content += s + b'\n'
        text = parse_content(content, page_font_map(head, objs), fonts)
        chunks.append('\n===== PAGE %d =====\n' % pi + text)
    out = '\n'.join(chunks)
    base = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(outdir, base + '.txt')
    open(dest, 'w', encoding='utf-8').write(out)
    return dest, len(out), len(pages), len(fonts)

if __name__ == '__main__':
    print(extract(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '.'))
