# Usage:
#   python3 isa/ref/sm90a/extract_opcodes.py > isa/ref/sm90a/opcodes.json
#
# Description:
#   Parses 'ref-encoding.json' to extract the 12-bit opcode for each instruction.
#   Outputs a JSON object mapping "Opcode.Name" to its binary representation string.
#

import json
import collections

# Configuration for sorting and display
# The script will sort primarily by the lower LOW_BITS_COUNT bits,
# and secondarily by the upper HIGH_BITS_COUNT bits.
LOW_BITS_COUNT = 9
HIGH_BITS_COUNT = 3  # Note: LOW_BITS_COUNT + HIGH_BITS_COUNT should equal 12

def get_opcode(ranges):
    opcode = 0
    for b in range(12):
        bit_val = 0
        for r in ranges:
            start = r['start']
            length = r['length']
            if start <= b < start + length:
                if r['type'] == 'constant' and r['constant'] is not None:
                    offset = b - start
                    bit_val = (int(r['constant']) >> offset) & 1
                # If not constant, treat as 0 (instruction variant / operand)
                break
        opcode |= (bit_val << b)
    return opcode

def to_bin_str(opcode):
    # 12 bits
    s = f"{opcode:012b}"
    # Original format: 4 bits per group (indices 0:4, 4:8, 8:12)
    # New requirement: Insert 2 spaces between the upper HIGH_BITS_COUNT and the rest.
    # For HIGH_BITS_COUNT=3, this cuts the first group [0:4] into [0:3] and [3:4].
    return f"{s[0:HIGH_BITS_COUNT]}  {s[HIGH_BITS_COUNT:4]} {s[4:8]} {s[8:12]}"

def main():
    try:
        with open('/home/mmy/work/gpidl/isa/ref/sm90a/ref-encoding.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("Error: File not found.")
        return

    extracted = []
    
    for key, val in data.items():
        if 'ranges' not in val or 'ranges' not in val['ranges']:
            continue
            
        ranges_list = val['ranges']['ranges']
        opcode = get_opcode(ranges_list)
        
        parts = key.split('.', 1)
        if len(parts) == 2:
            name_suffix = parts[1]
        else:
            name_suffix = key 
            
        new_key = f"{opcode}.{name_suffix}"
        bin_str = to_bin_str(opcode)
        
        extracted.append({'opcode': opcode, 'key': new_key, 'bin': bin_str})

    # Sort: First by lower LOW_BITS_COUNT bits, then by upper HIGH_BITS_COUNT bits
    low_mask = (1 << LOW_BITS_COUNT) - 1
    extracted.sort(key=lambda x: (
        x['opcode'] & low_mask,         # Primary sort key
        x['opcode'] >> LOW_BITS_COUNT   # Secondary sort key
    ))
    
    if not extracted:
        print("{}")
        return

    max_len = max(len(x['key']) for x in extracted)
    
    # Create an ordered dictionary to preserve sort order
    # Using a list of pairs for the ordered dict
    ordered_items = collections.OrderedDict()
    
    for item in extracted:
        padded_key = item['key'].ljust(max_len)
        ordered_items[padded_key] = item['bin']
        
    print(json.dumps(ordered_items, indent=4))

if __name__ == '__main__':
    main()
