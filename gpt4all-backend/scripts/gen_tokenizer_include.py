import sys
import json
from dataclasses import dataclass

def iter_with_last(lst):
    llen = len(lst)
    for i, entry in enumerate(lst):
        last = i == (llen - 1)
        yield last, entry

@dataclass
class BufSlice:
    offset: int
    length: int
    def __repr__(self):
        return '{'f'0x{self.offset:x},{self.length}''}'

def c_str_dump(bs):
    s = bytearray()
    s += b'"'
    llen = 0
    lasthex = False
    for byte in bs:
        if byte in (b' 01234567890abcdefghijklmnopqrstuvwxyz_-=/;:<>'
                    b'ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*(),.[]{}`~|'):
            # need to avoid hex characters not part of a hex escape
            # appearing directly after a hex scape
            if lasthex and byte in b'0123456789abcdefABCDEF':
                s += b'""'
                llen += 2
            s += bytes([byte])
            llen += 1
            lasthex = False
        else:
            s += f'\\x{byte:02x}'.encode('utf8')
            llen += 4
            lasthex = True
        if llen >= 80:
            llen = 0
            s += b"\"\n\""
    s += b'"'
    return s.decode('utf8')

class Buf:
    def __init__(self):
        self.buf = b''
        self.cache = {}

    def get(self, s):
        if s in self.cache:
            return self.cache[s]
        offset = len(self.buf)
        bs = s.encode('utf8')
        exoffs = self.buf.find(bs)
        if exoffs != -1:
            slc = BufSlice(offset=exoffs, length=len(bs))
            self.cache[s] = slc
            return slc
        return None

    def insert(self, s):
        slc = self.get(s)
        if slc is None:
            bs = s.encode('utf8')
            offset = len(self.buf)
            self.buf += bs
            slc = BufSlice(offset=offset, length=len(bs))
        return slc

class BreakEvery:
    def __init__(self, n):
        self.counter = 0
        self.n = n

    def __repr__(self):
        self.counter += 1
        self.counter %= self.n
        if self.counter == 0:
            return '\n'
        return ''

def do_convert(tkfilename, prefix):
    with open(tkfilename, 'rb') as tkf:
        tokconfig = json.load(tkf)

    # every string in the vocab also appears in the merges list so we can store
    # much less data in the binary by deduplicating these references, sorting by
    # length descending makes it more likely prefixes of longer strings get
    # deduped, and secondarily sorting lexicographically them makes the buffer
    # data more compressible (they are not compressed in the binary itself, but
    # the binary will be more compressible)
    split_merges = [s.split(' ') for s in tokconfig['model']['merges']]
    len_then = lambda m: (len(m),m)
    avwords = sorted((av['content'] for av in tokconfig['added_tokens']), key=len_then, reverse=True)
    all_strs = avwords + sorted(list(tokconfig['model']['vocab'].keys()), key=len_then, reverse=True)
    buf = Buf()
    for s in all_strs:
        buf.insert(s)

    print('// @generated GENERATED BY scripts/gen_tokenizer_include.py DO NOT MODIFY')
    print(f'#ifndef {prefix.upper()}_TOKENIZER_CONFIG_H_')
    print(f'#define {prefix.upper()}_TOKENIZER_CONFIG_H_')
    print('#include "bpe.h"')
    print(f"// buflen {len(buf.buf)}")
    print(f"constexpr const char {prefix}_buffer[] =\n{c_str_dump(buf.buf)};")
    avilen = len(tokconfig['added_tokens'])
    print(f'constexpr std::array<bpecpp::additional_vocab_item_embedded, {avilen}> {prefix}_additional_vocab = ''{{')
    for last, avi in iter_with_last(tokconfig['added_tokens']):
        comma = ',' if not last else '' 
        print('  {'f'.id = {avi["id"]}, .content={buf.get(avi["content"])}, .special={json.dumps(avi["special"])}''}' + comma) 
    print('}};')
    print()
    mergeslen = len(tokconfig['model']['merges'])
    print(f'constexpr std::array<std::pair<bpecpp::buf_ref, bpecpp::buf_ref>, {mergeslen}> {prefix}_merges = ''{{')
    breaker = BreakEvery(4)
    for last, (ma, mb) in iter_with_last(split_merges):
        comma = ',' if not last else '' 
        print('  {'f'{buf.get(ma)},{buf.get(mb)}''}' + comma + repr(breaker), end='')
    print('\n}};')
    vocablen = len(tokconfig['model']['vocab'])
    print(f'constexpr std::array<bpecpp::buf_ref, {vocablen}> {prefix}_vocab = ''{{')
    breaker = BreakEvery(8)
    for last, vi in iter_with_last(tokconfig['model']['vocab']):
        comma = ',' if not last else '' 
        print(f'  {buf.get(vi)}' + comma + repr(breaker), end='')
    print('\n}};')
    print(f'#endif // {prefix.upper()}_TOKENIZER_CONFIG_H_')

def main():
    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} <hf tokenizer json> <symbol prefix>')
        sys.exit(1)
    do_convert(sys.argv[1], sys.argv[2])

if __name__ == '__main__':
    main()