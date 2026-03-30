from pathlib import Path

def main():
    root_dir = Path(__file__).resolve().parent.parent
    vocab_dir = root_dir / "data" / "raw" / "vocab"
    
    # Map of pair_dir -> (vocab_col1, vocab_col2)
    # vocab columns are: ja (0), en (1), vi (2)
    
    # Store vocab pairs to inject
    # { pair_dir : set of (src, tgt) }
    inject_data = {
        "ja_en": set(),
        "en_vi": set(),
        "ja_vi": set()
    }
    
    # Read all vocab files
    vocab_files = vocab_dir.glob("*.tsv")
    for vfile in vocab_files:
        print(f"Reading vocab file: {vfile.name}")
        with open(vfile, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                continue
            
            # check header
            start_idx = 0
            if lines[0].strip("\n").split("\t") == ["ja", "en", "vi"]:
                start_idx = 1
                
            for line in lines[start_idx:]:
                line = line.strip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    ja, en, vi = parts[0].strip(), parts[1].strip(), parts[2].strip()
                    
                    if ja and en:
                        inject_data["ja_en"].add((ja, en))
                    if en and vi:
                        inject_data["en_vi"].add((en, vi))
                    if ja and vi:
                        inject_data["ja_vi"].add((ja, vi))
                        
    # For each pair_dir, read pairs.tsv, append new, write back
    for pair_dir, vocab_pairs in inject_data.items():
        pairs_file = root_dir / "data" / "raw" / pair_dir / "pairs.tsv"
        
        existing_pairs = set()
        existing_lines = []
        
        if pairs_file.exists():
            with open(pairs_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_strip = line.strip("\n")
                    if not line_strip:
                        continue
                    existing_lines.append(line_strip)
                    parts = line_strip.split("\t")
                    if len(parts) >= 2:
                        existing_pairs.add((parts[0].strip(), parts[1].strip()))
                        
        # Append new pairs
        added_count = 0
        with open(pairs_file, "a", encoding="utf-8") as f:
            for src, tgt in vocab_pairs:
                if (src, tgt) not in existing_pairs:
                    f.write(f"{src}\t{tgt}\n")
                    added_count += 1
                    existing_pairs.add((src, tgt))
                    
        print(f"[{pair_dir}] Injected {added_count} new vocabulary pairs.")

if __name__ == '__main__':
    main()
